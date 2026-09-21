"""
ATSC A/65 PSIP from a full MPEG-TS dump.

TVCT (0xC8) maps source_id to virtual channel. EIT (0xCB) is the schedule.
Times are GPS seconds, shown in America/New_York. Tuner 1 dumps unique
frequencies; a recording holds that tuner.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from engine.guide import epg_tuner_held
from engine.paths import CHANNELS_JSON_PATH, TIMESHIFT_DIR

TS_PACKET = 188
PSIP_PID = 0x1FFB
TABLE_TVCT = 0xC8
TABLE_EIT = 0xCB
GPS_UNIX_OFFSET = 315964800
GPS_LEAP_SECONDS = 18
EASTERN = ZoneInfo("America/New_York")
EPG_ADAPTER = 1
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
    return datetime.fromtimestamp(unix, tz=timezone.utc).astimezone(EASTERN)


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


def parse_multiple_string(data: bytes) -> str:
    if not data:
        return ""
    r = BitReader(data)
    nstrings = r.u(8)
    parts: List[str] = []
    for _ in range(nstrings):
        r.raw(3)
        nseg = r.u(8)
        for _ in range(nseg):
            compression = r.u(8)
            r.u(8)
            nbytes = r.u(8)
            chunk = r.raw(nbytes)
            if compression == 0:
                parts.append(chunk.decode("latin-1", "replace").strip("\x00").strip())
    return " ".join(p for p in parts if p)


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
    r = BitReader(section[8:] if len(section) > 8 else b"")
    r.u(8)
    nch = r.u(8)
    mapping: Dict[int, str] = {}
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
        r.u(16)
        r.u(16)
        source_id = r.u(16)
        r.u(6)
        dlen = r.u(10)
        r.raw(dlen)
        mapping[source_id] = f"{major}.{minor}"
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


def parse_atsc_ts(ts_data: bytes) -> Dict[str, List[Dict[str, Any]]]:
    sources: Dict[int, str] = {}
    by_source: Dict[int, List[Dict[str, Any]]] = {}
    for section in collect_sections(ts_data):
        if not section:
            continue
        table_id = section[0]
        if table_id == TABLE_TVCT:
            sources.update(parse_tvct(section))
        elif table_id == TABLE_EIT:
            parsed = parse_eit(section)
            sid = int(parsed["source_id"])
            by_source.setdefault(sid, []).extend(parsed["events"])
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
            merged.append(event)
        merged.sort(key=lambda e: int(e.get("gps_start") or 0))
    return programs


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
        try:
            proc.wait(timeout=max(20, int(dwell_sec) + 12))
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.terminate()
        if os.path.isfile(dest):
            with open(dest, "rb") as f:
                return f.read()
    return b""


def collect_guide_events(
    channels: Optional[List[Dict[str, Any]]] = None,
    dump_fn: Optional[Callable[[int, int], bytes]] = None,
    sessions: Optional[List[Any]] = None,
    adapter_id: int = EPG_ADAPTER,
) -> Dict[str, List[Dict[str, Any]]]:
    if epg_tuner_held(sessions):
        return {}
    from engine.tuner import TunerManager
    if dump_fn is None:
        tuners = {t.adapter_id: t for t in TunerManager.list_tuners()}
        tuner = tuners.get(adapter_id)
        if tuner is None or not tuner.supports_atsc or tuner.is_busy:
            return {}
    if channels is None:
        from engine.guide import _read_channels_file
        channels = _read_channels_file(CHANNELS_JSON_PATH)
    zap = dump_fn or (lambda _adapter, freq: dump_mux(adapter_id, freq))
    events: Dict[str, List[Dict[str, Any]]] = {}
    freqs = unique_frequencies(channels)
    for i, freq in enumerate(freqs, start=1):
        if dump_fn is None:
            print(f"EPG mux {i}/{len(freqs)} {freq} Hz", flush=True)
        try:
            raw = zap(adapter_id, freq) or b""
        except Exception as exc:
            if dump_fn is None:
                print(f"EPG mux {freq} Hz failed: {exc}", flush=True)
            continue
        parsed = parse_atsc_ts(raw)
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
        time.sleep(0)
    return events
