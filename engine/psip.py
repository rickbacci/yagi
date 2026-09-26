"""
ATSC A/65 PSIP from a full MPEG-TS dump.

TVCT (0xC8) maps source_id to virtual channel. EIT (0xCB) is the schedule.
ETT (0xCC) is the longer description, when the station sends one.
Times are GPS seconds, shown in this machine's zone. Tuner 1 dumps unique
frequencies; a recording holds that tuner.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from engine.atsc_huffman import decode_description, decode_title
from engine.guide import LOCAL_TZ, epg_tuner_held
from engine.paths import (
    CHANNELS_JSON_PATH,
    GUIDE_STATUS_PATH,
    TIMESHIFT_DIR,
    chmod_private_file,
    state_lock,
)
from engine.tuner import WORK_ADAPTER

TS_PACKET = 188
PSIP_PID = 0x1FFB
TABLE_TVCT = 0xC8
TABLE_EIT = 0xCB
TABLE_ETT = 0xCC
GPS_UNIX_OFFSET = 315964800
GPS_LEAP_SECONDS = 18
EPG_ADAPTER = WORK_ADAPTER
EPG_DWELL_SECS = 8.0


class BitWriter:
    def __init__(self) -> None:
        self._bits: List[int] = []

    def u(self, value: int, width: int) -> None:
        value = int(value) & ((1 << width) - 1)
        for i in range(width - 1, -1, -1):
            self._bits.append((value >> i) & 1)

    def raw(self, data: bytes) -> None:
        for byte in data:
            self.u(byte, 8)

    def to_bytes(self) -> bytes:
        bits = list(self._bits)
        while len(bits) % 8:
            bits.append(0)
        out = bytearray()
        for i in range(0, len(bits), 8):
            v = 0
            for b in bits[i : i + 8]:
                v = (v << 1) | b
            out.append(v)
        return bytes(out)


class BitReader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def u(self, width: int) -> int:
        value = 0
        for _ in range(width):
            if self.pos // 8 >= len(self.data):
                return value
            byte = self.data[self.pos // 8]
            bit = 7 - (self.pos % 8)
            value = (value << 1) | ((byte >> bit) & 1)
            self.pos += 1
        return value

    def raw(self, nbytes: int) -> bytes:
        out = bytearray()
        for _ in range(nbytes):
            out.append(self.u(8) & 0xFF)
        return bytes(out)

    def remaining(self) -> int:
        return max(0, len(self.data) * 8 - self.pos)


def mpeg_crc32(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for byte in data:
        crc ^= byte << 24
        for _ in range(8):
            if crc & 0x80000000:
                crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
            else:
                crc = (crc << 1) & 0xFFFFFFFF
    return crc


def gps_to_datetime(gps_seconds: int) -> datetime:
    unix = int(gps_seconds) + GPS_UNIX_OFFSET - GPS_LEAP_SECONDS
    return datetime.fromtimestamp(unix, tz=timezone.utc).astimezone(LOCAL_TZ)


def format_clock(dt: datetime) -> str:
    hour = dt.hour % 12 or 12
    ap = "AM" if dt.hour < 12 else "PM"
    return f"{hour}:{dt.minute:02d} {ap}"


def unique_frequencies(channels: Optional[List[Dict[str, Any]]]) -> List[int]:
    out: List[int] = []
    seen = set()
    for channel in channels or []:
        try:
            freq = int(channel.get("frequency") or 0)
        except (TypeError, ValueError):
            continue
        if freq <= 0 or freq in seen:
            continue
        seen.add(freq)
        out.append(freq)
    return out


def pack_multiple_string(text: str) -> bytes:
    raw = text.encode("latin-1", "replace")[:255]
    w = BitWriter()
    w.u(1, 8)
    w.raw(b"eng")
    w.u(1, 8)
    w.u(0, 8)
    w.u(0, 8)
    w.u(len(raw), 8)
    w.raw(raw)
    return w.to_bytes()


def parse_multiple_string(data: bytes, strip: bool = True) -> str:
    if not data:
        return ""
    r = BitReader(data)
    nstrings = r.u(8)
    # Each string is one language. Its segments are pieces of one text.
    strings: List[tuple] = []
    for _ in range(nstrings):
        lang = r.raw(3)
        nseg = r.u(8)
        pieces: List[str] = []
        for _ in range(nseg):
            compression = r.u(8)
            mode = r.u(8)
            nbytes = r.u(8)
            chunk = r.raw(nbytes)
            pieces.append(_segment_text(compression, mode, chunk))
        text = "".join(pieces)
        if strip:
            text = text.strip()
        if text.strip():
            strings.append((lang, text))
    for lang, text in strings:
        if lang == b"eng":
            return text
    return strings[0][1] if strings else ""


def _segment_text(compression: int, mode: int, chunk: bytes) -> str:
    if compression == 0:
        # A/65 mode: 0x3F is UTF-16; 0x00-0x33 picks the Unicode page, each
        # byte is the low half of the code point. 0x00 is Latin-1.
        if mode == 0x3F:
            text = chunk[: len(chunk) - (len(chunk) % 2)].decode("utf-16-be", "replace")
        elif mode <= 0x33:
            text = "".join(chr((mode << 8) | b) for b in chunk)
        elif mode == 0xFF:
            text = chunk.decode("latin-1", "replace")
        else:
            return ""
        return text.strip("\x00")
    if compression == 1 and mode in (0, 0xFF):
        return decode_title(chunk).strip()
    if compression == 2 and mode in (0, 0xFF):
        return decode_description(chunk).strip()
    return ""


def _private_section(table_id: int, body_after_length: bytes) -> bytes:
    length = len(body_after_length) + 4
    header = BitWriter()
    header.u(table_id, 8)
    header.u(1, 1)
    header.u(1, 1)
    header.u(3, 2)
    header.u(length, 12)
    prefix = header.to_bytes() + body_after_length
    crc = mpeg_crc32(prefix)
    return prefix + crc.to_bytes(4, "big")


def pack_tvct_section(channels: List[Dict[str, Any]], tsid: int = 1) -> bytes:
    body = BitWriter()
    body.u(tsid, 16)
    body.u(3, 2)
    body.u(1, 5)
    body.u(1, 1)
    body.u(0, 8)
    body.u(0, 8)
    body.u(0, 8)
    body.u(len(channels), 8)
    for ch in channels:
        name = str(ch.get("short_name") or ch.get("callsign") or "OTA")[:7]
        utf16 = name.encode("utf-16-be")
        utf16 = (utf16 + (b"\x00\x20" * 7))[:14]
        body.raw(utf16)
        body.u(0xF, 4)
        body.u(int(ch["major"]), 10)
        body.u(int(ch["minor"]), 10)
        body.u(4, 8)
        body.u(0, 32)
        body.u(tsid, 16)
        body.u(int(ch.get("program_number") or 1), 16)
        body.u(0, 2)
        body.u(0, 1)
        body.u(0, 1)
        body.u(3, 2)
        body.u(0, 1)
        body.u(7, 3)
        body.u(2, 6)
        body.u(int(ch["source_id"]), 16)
        body.u(0x3F, 6)
        body.u(0, 10)
    body.u(0x3F, 6)
    body.u(0, 10)
    return _private_section(TABLE_TVCT, body.to_bytes())


def pack_eit_section(source_id: int, events: List[Dict[str, Any]]) -> bytes:
    body = BitWriter()
    body.u(source_id, 16)
    body.u(3, 2)
    body.u(1, 5)
    body.u(1, 1)
    body.u(0, 8)
    body.u(0, 8)
    body.u(0, 8)
    body.u(len(events), 8)
    for i, ev in enumerate(events):
        title = pack_multiple_string(str(ev.get("title") or "Program"))
        body.u(3, 2)
        body.u(int(ev.get("event_id") or (i + 1)), 14)
        body.u(int(ev["gps_start"]), 32)
        body.u(3, 2)
        body.u(0, 2)
        body.u(int(ev["duration_sec"]), 20)
        body.u(len(title), 8)
        body.raw(title)
        body.u(0xF, 4)
        body.u(0, 12)
    return _private_section(TABLE_EIT, body.to_bytes())


def pack_ett_section(source_id: int, event_id: int, text: str, section_number: int = 0, last_section: int = 0) -> bytes:
    """Event ETM. The two low bits of ETM_id are 10; a channel ETM uses 00."""
    etm_id = ((int(source_id) & 0xFFFF) << 16) | ((int(event_id) & 0x3FFF) << 2) | 0b10
    body = BitWriter()
    body.u(0, 16)
    body.u(3, 2)
    body.u(1, 5)
    body.u(1, 1)
    body.u(section_number, 8)
    body.u(last_section, 8)
    body.u(0, 8)
    body.u(etm_id, 32)
    body.raw(pack_multiple_string(text))
    return _private_section(TABLE_ETT, body.to_bytes())


def section_to_ts(section: bytes, pid: int = PSIP_PID) -> bytes:
    packets = bytearray()
    remaining = bytes([0]) + section
    first = True
    cc = 0
    while remaining:
        chunk = remaining[:184]
        remaining = remaining[184:]
        if len(chunk) < 184:
            chunk = chunk + bytes([0xFF] * (184 - len(chunk)))
        pusi = 0x40 if first else 0
        first = False
        packets.extend(bytes([
            0x47,
            pusi | ((pid >> 8) & 0x1F),
            pid & 0xFF,
            0x10 | (cc & 0xF),
        ]))
        packets.extend(chunk)
        cc = (cc + 1) & 0xF
    return bytes(packets)


def collect_sections(ts_data: bytes) -> List[bytes]:
    buf: Dict[int, bytearray] = {}
    sections: List[bytes] = []

    def finish(pid: int) -> None:
        data = buf.get(pid)
        if not data or len(data) < 3:
            return
        length = ((data[1] & 0x0F) << 8) | data[2]
        need = 3 + length
        if len(data) < need:
            return
        section = bytes(data[:need])
        if mpeg_crc32(section[:-4]) == int.from_bytes(section[-4:], "big"):
            sections.append(section)
        leftover = data[need:]
        buf[pid] = leftover if leftover else bytearray()

    i = 0
    while i + TS_PACKET <= len(ts_data):
        pkt = ts_data[i : i + TS_PACKET]
        i += TS_PACKET
        if pkt[0] != 0x47:
            continue
        pid = ((pkt[1] & 0x1F) << 8) | pkt[2]
        afc = (pkt[3] >> 4) & 0x3
        pos = 4
        if afc in (2, 3):
            alen = pkt[pos]
            pos += 1 + alen
        if afc in (0, 2) or pos >= TS_PACKET:
            continue
        payload = pkt[pos:]
        pusi = bool(pkt[1] & 0x40)
        if pusi:
            pointer = payload[0]
            payload = payload[1:]
            if pid in buf and buf[pid]:
                if pointer:
                    buf[pid].extend(payload[:pointer])
                finish(pid)
                payload = payload[pointer:]
            buf[pid] = bytearray(payload)
        else:
            buf.setdefault(pid, bytearray()).extend(payload)
        finish(pid)
    for pid in list(buf):
        finish(pid)
    return sections


def parse_tvct(section: bytes) -> Dict[int, str]:
    return {sid: row["number"] for sid, row in parse_tvct_rows(section).items()}


def parse_tvct_rows(section: bytes) -> Dict[int, Dict[str, Any]]:
    """source_id to the broadcast's channel number and its MPEG program number."""
    r = BitReader(section[8:] if len(section) > 8 else b"")
    r.u(8)
    nch = r.u(8)
    mapping: Dict[int, Dict[str, Any]] = {}
    for _ in range(nch):
        raw_name = r.raw(14)
        try:
            short = raw_name.decode("utf-16-be").replace("\x00", "").strip()
        except Exception:
            short = ""
        r.u(4)
        major = r.u(10)
        minor = r.u(10)
        r.u(8)
        r.u(32)
        r.u(16)
        program_number = r.u(16)
        r.u(16)
        source_id = r.u(16)
        r.u(6)
        dlen = r.u(10)
        r.raw(dlen)
        mapping[source_id] = {"number": f"{major}.{minor}", "program": program_number}
        _ = short
    return mapping


def parse_eit(section: bytes) -> Dict[str, Any]:
    r = BitReader(section[3:] if len(section) > 3 else b"")
    source_id = r.u(16)
    r.u(2)
    r.u(5)
    r.u(1)
    r.u(8)
    r.u(8)
    r.u(8)
    n_ev = r.u(8)
    events: List[Dict[str, Any]] = []
    for _ in range(n_ev):
        r.u(2)
        event_id = r.u(14)
        gps_start = r.u(32)
        r.u(2)
        r.u(2)
        duration = r.u(20)
        tlen = r.u(8)
        title = parse_multiple_string(r.raw(tlen))
        r.u(4)
        dlen = r.u(12)
        r.raw(dlen)
        start_dt = gps_to_datetime(gps_start)
        end_dt = gps_to_datetime(gps_start + duration)
        events.append({
            "event_id": event_id,
            "title": title or "Program",
            "start": format_clock(start_dt),
            "end": format_clock(end_dt),
            "gps_start": gps_start,
            "duration_sec": duration,
        })
    return {"source_id": source_id, "events": events}


def parse_ett(section: bytes) -> Dict[str, Any]:
    """One extended-text section. Event messages use ETM_id low bits 10."""
    if len(section) < 17:
        return {}
    r = BitReader(section[3:])
    r.u(16)
    r.u(2)
    r.u(5)
    r.u(1)
    section_number = r.u(8)
    r.u(8)
    r.u(8)
    etm_id = r.u(32)
    # Kept as sent. A long text splits across sections, sometimes at a space.
    text = parse_multiple_string(section[13:-4], strip=False)
    return {
        "source_id": (etm_id >> 16) & 0xFFFF,
        "event_id": (etm_id >> 2) & 0x3FFF,
        "is_event": (etm_id & 0x3) == 0b10,
        "section_number": section_number,
        "text": text,
    }


def parse_atsc_ts(
    ts_data: bytes,
    lineup_by_program: Optional[Dict[int, str]] = None,
    sections: Optional[List[bytes]] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Listings keyed by channel number.

    lineup_by_program maps this tower's program numbers to the saved lineup's
    channel numbers. A station map can renumber a tower (the air says 35.1,
    the lineup says 65.1); the program number is the same on both.
    """
    sources: Dict[int, str] = {}
    by_source: Dict[int, List[Dict[str, Any]]] = {}
    descriptions: Dict[tuple, List[tuple]] = {}
    for section in sections if sections is not None else collect_sections(ts_data):
        if not section:
            continue
        table_id = section[0]
        if table_id == TABLE_TVCT:
            for source_id, row in parse_tvct_rows(section).items():
                mapped = (lineup_by_program or {}).get(int(row["program"]))
                sources[source_id] = mapped or row["number"]
        elif table_id == TABLE_EIT:
            parsed = parse_eit(section)
            sid = int(parsed["source_id"])
            by_source.setdefault(sid, []).extend(parsed["events"])
        elif table_id == TABLE_ETT:
            ett = parse_ett(section)
            if ett.get("is_event") and ett.get("text"):
                key = (int(ett["source_id"]), int(ett["event_id"]))
                descriptions.setdefault(key, []).append((int(ett["section_number"]), ett["text"]))
    programs: Dict[str, List[Dict[str, Any]]] = {}
    for source_id, events in by_source.items():
        number = sources.get(source_id) or str(source_id)
        merged = programs.setdefault(number, [])
        seen = {(e.get("gps_start"), e.get("title")) for e in merged}
        for event in events:
            key = (event.get("gps_start"), event.get("title"))
            if key in seen:
                continue
            seen.add(key)
            blurb = _event_description(descriptions, source_id, event.get("event_id"))
            if blurb:
                event = dict(event)
                event["synopsis"] = blurb
            merged.append(event)
        merged.sort(key=lambda e: int(e.get("gps_start") or 0))
    return programs


def _event_description(descriptions: Dict[tuple, List[tuple]], source_id: int, event_id: Any) -> str:
    parts = descriptions.get((int(source_id), int(event_id or 0))) or []
    if not parts:
        return ""
    # Stations repeat each section many times. One copy per section number.
    by_section: Dict[int, str] = {}
    for number, text in parts:
        by_section.setdefault(int(number), text)
    return "".join(by_section[n] for n in sorted(by_section)).strip()


class GuideYield(Exception):
    """Live TV asked for this tuner mid-tower."""


def dump_mux(adapter_id: int, frequency: int, dwell_sec: float = EPG_DWELL_SECS) -> bytes:
    from engine.timeshift import Timeshift
    Timeshift._wait_frontend_free(timeout=0.8, adapter_id=adapter_id)
    os.makedirs(os.path.dirname(TIMESHIFT_DIR) or ".", exist_ok=True)
    epg_dir = os.path.join(os.path.dirname(TIMESHIFT_DIR), "epg")
    os.makedirs(epg_dir, mode=0o700, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=epg_dir) as tmp:
        conf_path = os.path.join(tmp, "epg.conf")
        dest = os.path.join(tmp, "psip.ts")
        with open(conf_path, "w", encoding="utf-8") as f:
            f.write("[EPG]\n")
            f.write("  DELIVERY_SYSTEM = ATSC\n")
            f.write(f"  FREQUENCY = {int(frequency)}\n")
            f.write("  MODULATION = VSB/8\n")
        cmd = [
            "dvbv5-zap",
            "-a", str(adapter_id),
            "-c", conf_path,
            "-I", "dvbv5",
            "-r",
            "-P",
            "-t", str(max(2, int(dwell_sec))),
            "-o", dest,
            "EPG",
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        from engine import pool
        deadline = time.time() + max(20, int(dwell_sec) + 12)
        try:
            while proc.poll() is None and time.time() < deadline:
                if pool.guide_must_yield(adapter_id):
                    raise GuideYield()
                time.sleep(0.2)
        finally:
            if proc.poll() is None:
                proc.kill()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
        if os.path.isfile(dest):
            with open(dest, "rb") as f:
                return f.read()
    return b""


def _guide_tuner(sessions: Optional[List[Any]], preferred: Optional[int]) -> Optional[int]:
    """A tuner nothing else holds, for one tower. Tests pass sessions and a fixed tuner."""
    if sessions is not None:
        return None if epg_tuner_held(sessions) else preferred
    from engine import pool
    held = {a: job for a, job in pool.claims().items() if job != "guide"}
    if preferred is not None:
        return None if preferred in held else preferred
    return pool.pick_work(held, wait_for_guide=False)


def collect_guide_events(
    channels: Optional[List[Dict[str, Any]]] = None,
    dump_fn: Optional[Callable[[int, int], bytes]] = None,
    sessions: Optional[List[Any]] = None,
    adapter_id: Optional[int] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Read every tower's listings on whichever tuner is free, one tower per hold.

    A recording that wants the tuner gets it between towers. Live TV gets it mid-tower.
    """
    from engine import pool
    if dump_fn is not None and adapter_id is None:
        adapter_id = EPG_ADAPTER
    if _guide_tuner(sessions, adapter_id) is None:
        return {}
    if channels is None:
        from engine.guide import _read_channels_file
        channels = _read_channels_file(CHANNELS_JSON_PATH)
    zap = dump_fn or dump_mux
    events: Dict[str, List[Dict[str, Any]]] = {}
    freqs = unique_frequencies(channels)
    live = dump_fn is None
    try:
        for i, freq in enumerate(freqs, start=1):
            tuner = _guide_tuner(sessions, adapter_id)
            if tuner is None:
                break
            if live:
                write_guide_status(True, i, len(freqs), adapter=tuner)
            with state_lock(pool.lock_key(tuner)):
                if _guide_tuner(sessions, tuner) is None:
                    break
                if live:
                    print(f"EPG mux {i}/{len(freqs)} {freq} Hz on tuner {tuner}", flush=True)
                try:
                    raw = zap(tuner, freq) or b""
                except GuideYield:
                    if live:
                        print(f"EPG gave tuner {tuner} to live TV", flush=True)
                    time.sleep(1.0)
                    continue
                except Exception as exc:
                    if live:
                        print(f"EPG mux {freq} Hz failed: {exc}", flush=True)
                    continue
            sections = collect_sections(raw)
            if live:
                time.sleep(0.3)
                learned = parse_pmt_pids(raw, sections)
                if learned:
                    from engine.timeshift import Timeshift
                    try:
                        Timeshift._write_learned_pids(learned, freq, trust=True)
                    except OSError:
                        pass
            parsed = parse_atsc_ts(raw, lineup_programs(channels, freq), sections)
            for number, programs in parsed.items():
                bucket = events.setdefault(number, [])
                seen = {(p.get("gps_start"), p.get("title")) for p in bucket}
                for prog in programs:
                    key = (prog.get("gps_start"), prog.get("title"))
                    if key in seen:
                        continue
                    seen.add(key)
                    bucket.append(prog)
                bucket.sort(key=lambda e: int(e.get("gps_start") or 0))
    finally:
        if live:
            write_guide_status(False, 0, len(freqs))
    return events


# PMT stream types: MPEG-2, H.264, HEVC video; MPEG, AAC, AC-3, E-AC-3 audio.
_VIDEO_TYPES = {0x01, 0x02, 0x1B, 0x24}
_AUDIO_TYPES = {0x03, 0x04, 0x0F, 0x11, 0x81, 0x87}


def parse_pmt_pids(ts_data: bytes, sections: Optional[List[bytes]] = None) -> Dict[int, tuple]:
    """Program number to (video, audio) from the tower's own PMTs.

    The scan's IDs can be another service's. The PMT is what the tower sends.
    """
    out: Dict[int, tuple] = {}
    for s in sections if sections is not None else collect_sections(ts_data):
        if not s or s[0] != 0x02 or len(s) < 16:
            continue
        program = (s[3] << 8) | s[4]
        end = min(len(s), 3 + (((s[1] & 0x0F) << 8) | s[2])) - 4
        i = 12 + (((s[10] & 0x0F) << 8) | s[11])
        video = audio = 0
        while i + 5 <= end:
            kind = s[i]
            pid = ((s[i + 1] & 0x1F) << 8) | s[i + 2]
            if kind in _VIDEO_TYPES and not video:
                video = pid
            elif kind in _AUDIO_TYPES and not audio:
                audio = pid
            i += 5 + (((s[i + 3] & 0x0F) << 8) | s[i + 4])
        if program > 0 and video and audio:
            out[program] = (video, audio)
    return out


def lineup_programs(channels: Optional[List[Dict[str, Any]]], frequency: int) -> Dict[int, str]:
    """Program number to lineup channel number, for one tower. A number used twice is left out."""
    found: Dict[int, List[str]] = {}
    for ch in channels or []:
        try:
            if int(ch.get("frequency") or 0) != int(frequency):
                continue
            program = int(ch.get("service_id") or 0)
        except (TypeError, ValueError):
            continue
        number = str(ch.get("channel_number") or "").strip()
        if program > 0 and number:
            found.setdefault(program, []).append(number)
    return {program: nums[0] for program, nums in found.items() if len(set(nums)) == 1}


def write_guide_status(
    running: bool, tower: int, towers: int, path: Optional[str] = None, adapter: Optional[int] = None,
) -> None:
    """What the flyout shows while a Guide update runs, and which tuner it holds."""
    target = path or GUIDE_STATUS_PATH
    payload = {
        "running": bool(running),
        "pid": os.getpid() if running else 0,
        "tower": int(tower),
        "towers": int(towers),
        "adapter": adapter if running else None,
        "updated_at": time.time(),
    }
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        tmp = f"{target}.tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        chmod_private_file(tmp)
        os.replace(tmp, target)
    except OSError:
        pass


def guide_update_running(path: Optional[str] = None) -> bool:
    try:
        with open(path or GUIDE_STATUS_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and bool(data.get("running"))


def clear_stale_guide_status(path: Optional[str] = None) -> bool:
    """A killed update leaves running=true. Its pid tells."""
    target = path or GUIDE_STATUS_PATH
    try:
        with open(target, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict) or not data.get("running"):
        return False
    pid = int(data.get("pid") or 0)
    if pid > 0:
        try:
            os.kill(pid, 0)
            return False
        except ProcessLookupError:
            pass
        except PermissionError:
            return False
    write_guide_status(False, 0, int(data.get("towers") or 0), path=target)
    return True
