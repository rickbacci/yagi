"""yagi signal check: signal to noise and damaged packets for one channel, a line every few seconds.

The tuner flags each transport packet it could not repair (transport_error_indicator).
A handful of flagged packets is a glitch on screen; a steady stream is artifacts.
On the tower live TV holds, this reads the live tuner and the live dump. Anywhere
else it takes a free tuner under that tuner's lock, as a scan does, and lets go.

favorites and all walk the saved lineup once per tower. Subchannels share a carrier,
so a second tune of the same frequency would only repeat the first reading.
"""

import os
import statistics
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from engine import pool
from engine.paths import (
    CHANNELS_JSON_PATH, FAVORITES_JSON_PATH, SIGNAL_LOG_PATH, TIMESHIFT_FILE,
    state_lock,
)

TS_PACKET = 188
SYNC = 0x47
INTERVAL_SEC = 2.0
MAX_SECONDS = 600
SURVEY_SECONDS = 16
EASTERN = ZoneInfo("America/New_York")
READ_CHUNK = 1 << 20
JOB_TEXT = {"live": " with live TV on another tower", "record": " recording",
            "scan": " scanning", "guide": " updating the Guide"}


def count_damaged(data: bytes, carry: bytes = b"") -> Tuple[int, int, bytes]:
    """Packets and flagged packets in data, plus the partial packet to carry into the next read."""
    buf = carry + data
    packets = damaged = 0
    i, n = 0, len(buf)
    while i + TS_PACKET <= n:
        if buf[i] != SYNC:
            i += 1
            continue
        packets += 1
        if buf[i + 1] & 0x80:
            damaged += 1
        i += TS_PACKET
    return packets, damaged, buf[i:] if n - i < TS_PACKET else b""


def verdict(windows: int, damaged_windows: int) -> str:
    if damaged_windows == 0:
        return "Clean."
    if damaged_windows * 10 <= windows:
        return "A glitch now and then."
    return "Damaged often: expect artifacts."


def _channel(query: str, channels_path: str) -> Optional[Dict[str, Any]]:
    import json
    from engine.enrichment import match_channel

    try:
        with open(channels_path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return None
    channels = raw.get("channels", []) if isinstance(raw, dict) else raw
    return match_channel(query, channels) if channels else None


def _live_source(freq: int) -> Optional[Tuple[int, str]]:
    from engine.timeshift import Timeshift

    state = Timeshift.load_state()
    if state.get("running") and int(state.get("freq") or 0) == freq:
        return int(state.get("adapter_id") or 0), str(state.get("path") or TIMESHIFT_FILE)
    return None


def _follow(path: str) -> Callable[[], bytes]:
    f = open(path, "rb")
    f.seek(0, os.SEEK_END)

    def read() -> bytes:
        if os.path.getsize(path) < f.tell():
            f.seek(0)
        return f.read(64 * READ_CHUNK)
    return read


def _watch(adapter: int, read: Callable[[], bytes], seconds: int, say: Callable[[str], None]) -> Dict[str, Any]:
    from engine.tuner import TunerManager

    snr: List[float] = []
    windows = damaged_windows = total = bad = 0
    carry = b""
    stopped = False
    stop = time.time() + seconds
    try:
        while time.time() < stop:
            time.sleep(INTERVAL_SEC)
            packets, damaged, carry = count_damaged(read(), carry)
            reading = TunerManager.read_signal(adapter) or {}
            db = reading.get("snr_db") if reading.get("locked") else None
            windows += 1
            total += packets
            bad += damaged
            if damaged:
                damaged_windows += 1
            if db is not None:
                snr.append(float(db))
            level = f"C/N {db:4.1f} dB" if db is not None else "no lock    "
            state = f"{damaged} damaged packets" if damaged else ("clean" if packets else "no data")
            say(f"{time.strftime('%H:%M:%S')}  {level}  {state}")
    except KeyboardInterrupt:
        stopped = True
    return {"snr": snr, "windows": windows, "damaged_windows": damaged_windows,
            "packets": total, "damaged": bad, "stopped": stopped}


def check(query: str, seconds: int = 30, say: Callable[[str], None] = print,
          channels_path: str = CHANNELS_JSON_PATH, adapter: Optional[int] = None) -> Dict[str, Any]:
    """adapter: read that tuner. Live TV's tuner on this tower reads the live dump; any other must be free."""
    ch = _channel(query, channels_path)
    if not ch or not ch.get("frequency"):
        raise ValueError(f"No channel matches {query!r}. See: yagi list")
    freq = int(ch["frequency"])
    name = f"{ch.get('channel_number', '')} {ch.get('display_name') or ch.get('name') or ''}".strip()
    seconds = max(int(INTERVAL_SEC), min(MAX_SECONDS, int(seconds)))

    live = _live_source(freq)
    if live and adapter is not None and adapter != live[0]:
        live = None
    if live:
        adapter, path = live
        say(f"{name}: reading live TV on tuner {adapter} for {seconds} s. Ctrl+C stops.")
        result = _watch(adapter, _follow(path), seconds, say)
    else:
        from engine.tuner import TunerManager

        named = adapter is not None
        if named and not os.path.exists(f"/dev/dvb/adapter{adapter}"):
            raise ValueError(f"There is no tuner {adapter}. See: yagi status")
        if not named:
            adapter = pool.pick_work(wait_for_guide=False)
        if adapter is None:
            raise RuntimeError(pool.busy_text())
        with state_lock(pool.lock_key(adapter), timeout=0.5):
            job = pool.claims().get(adapter)
            if job or not TunerManager.adapter_is_free(adapter):
                if not named:
                    raise RuntimeError(pool.busy_text())
                raise RuntimeError(f"Tuner {adapter} is busy{JOB_TEXT.get(job, '')}.")
            from engine.tower_dump import LOCK_TIMEOUT_SEC, Tuner

            tuner = Tuner(int(adapter))
            try:
                if not tuner.tune(freq, LOCK_TIMEOUT_SEC):
                    raise RuntimeError(f"No lock at {freq} Hz")
                tuner.start()

                def read() -> bytes:
                    parts = []
                    while True:
                        chunk = tuner.read()
                        if not chunk:
                            break
                        parts.append(chunk)
                    return b"".join(parts)

                say(f"{name}: tuner {adapter} for {seconds} s. Ctrl+C stops.")
                result = _watch(adapter, read, seconds, say)
            finally:
                try:
                    tuner.stop()
                except OSError:
                    pass
                tuner.close()

    snr = result["snr"]
    if snr:
        say(f"C/N {statistics.mean(snr):.1f} dB average ({min(snr):.1f}–{max(snr):.1f}). 8VSB breaks up near 15.")
    pct = 100.0 * result["damaged"] / result["packets"] if result["packets"] else 0.0
    say(f"{result['damaged_windows']} of {result['windows']} readings damaged, "
        f"{result['damaged']:,} damaged packets ({pct:.3f}%). {verdict(result['windows'], result['damaged_windows'])}")
    return dict(result, channel=name, adapter=adapter, live=bool(live))


def rf_number(freq: int) -> Optional[int]:
    """ATSC RF channel for a pilot frequency. Channel 8 is 183028615."""
    mhz = (int(freq) - 28615) / 1_000_000

    def whole(channel: float) -> Optional[int]:
        rounded = round(channel)
        return int(rounded) if abs(channel - rounded) < 0.01 else None

    if 177 <= mhz <= 213:
        return whole(7 + (mhz - 177) / 6)
    if mhz >= 473:
        return whole(14 + (mhz - 473) / 6)
    return {57: 2, 63: 3, 69: 4, 79: 5, 85: 6}.get(round(mhz))


def rf_band(rf: Optional[int]) -> str:
    if rf is None:
        return ""
    if rf <= 6:
        return "VHF-Low"
    if rf <= 13:
        return "VHF"
    return "UHF"


def _load_channels(path: str) -> List[Dict[str, Any]]:
    import json
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return []
    rows = raw.get("channels", []) if isinstance(raw, dict) else raw
    return [ch for ch in rows if isinstance(ch, dict)] if isinstance(rows, list) else []


def _row(ch: Dict[str, Any], also: List[str]) -> Dict[str, Any]:
    freq = int(ch["frequency"])
    rf = rf_number(freq)
    number = str(ch.get("channel_number") or "")
    name = ch.get("display_name") or ch.get("name") or ""
    return {
        "query": number or name,
        "label": f"{number} {name}".strip(),
        "frequency": freq,
        "rf": rf,
        "band": rf_band(rf),
        "also": also,
    }


def plan(which: str, channels_path: str = CHANNELS_JSON_PATH,
         favorites_path: str = FAVORITES_JSON_PATH) -> Tuple[List[Dict[str, Any]], List[str]]:
    """One row per tower. Favorites keep file order; all towers sort by RF channel."""
    from engine.favorites import load_favorites

    channels = _load_channels(channels_path)
    by_freq: Dict[int, List[Dict[str, Any]]] = {}
    for ch in channels:
        if ch.get("frequency"):
            by_freq.setdefault(int(ch["frequency"]), []).append(ch)
    favs = load_favorites(favorites_path, channels_path)

    def on_tower(freq: int, number: str) -> bool:
        return any(str(ch.get("channel_number") or "") == number for ch in by_freq.get(freq, []))

    if which == "all":
        rows = []
        for freq, group in by_freq.items():
            starred = [n for n in favs if on_tower(freq, n)]
            lead = group[0]
            for number in starred:
                match = next((ch for ch in group if str(ch.get("channel_number") or "") == number), None)
                if match is not None:
                    lead = match
                    break
            if not starred:
                lead = next((ch for ch in group if str(ch.get("channel_number") or "").endswith(".1")), group[0])
            lead_number = str(lead.get("channel_number") or "")
            rows.append(_row(lead, [n for n in starred if n != lead_number]))
        rows.sort(key=lambda row: (row["rf"] is None, row["rf"] or 0, row["frequency"]))
        return rows, []

    rows = []
    missing: List[str] = []
    seen = set()
    for number in favs:
        match = next((ch for ch in channels if str(ch.get("channel_number") or "") == number and ch.get("frequency")), None)
        if match is None:
            missing.append(number)
            continue
        freq = int(match["frequency"])
        if freq in seen:
            continue
        seen.add(freq)
        rows.append(_row(match, [n for n in favs if n != number and on_tower(freq, n)]))
    return rows, missing


def eastern_stamp(when: Optional[datetime] = None) -> str:
    now = when or datetime.now(EASTERN)
    now = now.astimezone(EASTERN) if now.tzinfo else now.replace(tzinfo=EASTERN)
    return now.strftime("%Y-%m-%d %H:%M ") + (now.tzname() or "ET")


def format_block(done: List[Tuple[Dict[str, Any], Dict[str, Any]]], title: str,
                 when: Optional[datetime] = None, seconds: int = SURVEY_SECONDS) -> str:
    lines = [f"{eastern_stamp(when)}  {title}"]
    for row, result in done:
        snr = result.get("snr") or []
        level = (f"{statistics.mean(snr):.1f} dB ({min(snr):.1f}–{max(snr):.1f})" if snr else "no lock")
        where = f"RF {row['rf']:<2} {row['band']:<4}" if row.get("rf") else f"{row['frequency']}"
        tuner = result.get("adapter")
        tuner_text = f"tuner {tuner}" if tuner is not None else "tuner ?"
        also = f"  also {', '.join(row['also'])}" if row.get("also") else ""
        lines.append(
            f"  {where}  {row['label']:<22} {level:<22} {int(result.get('damaged') or 0)} damaged  "
            f"{tuner_text}  {seconds}s{also}"
        )
    return "\n".join(lines) + "\n"


def append_block(path: str, block: str) -> None:
    """Add a block. Leave every older block as it was."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    prefix = ""
    if os.path.exists(path) and os.path.getsize(path):
        with open(path, "rb") as f:
            f.seek(-1, os.SEEK_END)
            if f.read(1) != b"\n":
                prefix = "\n"
        prefix += "\n"
    else:
        prefix = (
            "# Signal checks. Append a block. Do not rewrite old ones.\n"
            "# One channel does not write here. `yagi signal check favorites` and `all` append a block.\n"
            "# The lineup scan is channels.json.\n\n"
        )
    with open(path, "a", encoding="utf-8") as f:
        f.write(prefix + block)


def survey(which: str, seconds: int = SURVEY_SECONDS, note: str = "",
           say: Callable[[str], None] = print, channels_path: str = CHANNELS_JSON_PATH,
           favorites_path: str = FAVORITES_JSON_PATH, adapter: Optional[int] = None,
           log_path: Optional[str] = SIGNAL_LOG_PATH,
           when: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Measure each tower. Ctrl+C keeps the towers already finished and appends them."""
    if which not in ("favorites", "all"):
        raise ValueError("Survey favorites or all.")
    rows, missing = plan(which, channels_path, favorites_path)
    for number in missing:
        say(f"{number} is not in the lineup.")
    if not rows:
        if which == "favorites":
            raise ValueError("No favorite channels saved. Add one with: yagi favorite toggle 8.1")
        raise ValueError("No channels saved. Run: yagi scan")
    seconds = max(int(INTERVAL_SEC), min(MAX_SECONDS, int(seconds)))
    say(f"{len(rows)} towers, {seconds} s each. One tune per carrier. Ctrl+C stops.")
    done: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    error: Optional[BaseException] = None
    for row in rows:
        say("")
        try:
            result = check(row["query"], seconds=seconds, say=say, channels_path=channels_path, adapter=adapter)
        except (ValueError, RuntimeError) as exc:
            error = exc
            break
        done.append((row, result))
        if result.get("stopped"):
            break
    if done and log_path:
        title = " ".join(str(note or "").split())
        if not title:
            title = "favorites" if which == "favorites" else "all towers"
        if error or any(result.get("stopped") for _, result in done):
            title += ", stopped"
        block = format_block(done, title, when, seconds)
        append_block(log_path, block)
        say("")
        say(block.rstrip("\n"))
        say(f"Appended to {log_path}")
    if error:
        raise error
    return [result for _, result in done]
