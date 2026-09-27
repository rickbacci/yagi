"""yagi signal check: signal to noise and damaged packets for one channel, a line every few seconds.

The tuner flags each transport packet it could not repair (transport_error_indicator).
A handful of flagged packets is a glitch on screen; a steady stream is artifacts.
On the tower live TV holds, this reads the live tuner and the live dump. Anywhere
else it takes a free tuner under that tuner's lock, as a scan does, and lets go.
"""

import os
import select
import statistics
import subprocess
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from engine import pool
from engine.paths import CHANNELS_JSON_PATH, TIMESHIFT_FILE, get_runtime_socket, state_lock

TS_PACKET = 188
SYNC = 0x47
INTERVAL_SEC = 2.0
MAX_SECONDS = 600
READ_CHUNK = 1 << 20


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


def _pipe(proc: subprocess.Popen) -> Callable[[], bytes]:
    fd = proc.stdout.fileno()

    def read() -> bytes:
        out = []
        while select.select([fd], [], [], 0)[0]:
            chunk = os.read(fd, READ_CHUNK)
            if not chunk:
                break
            out.append(chunk)
        return b"".join(out)
    return read


def _watch(adapter: int, read: Callable[[], bytes], seconds: int, say: Callable[[str], None]) -> Dict[str, Any]:
    from engine.tuner import TunerManager

    snr: List[float] = []
    windows = damaged_windows = total = bad = 0
    carry = b""
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
        pass
    return {"snr": snr, "windows": windows, "damaged_windows": damaged_windows, "packets": total, "damaged": bad}


def check(query: str, seconds: int = 30, say: Callable[[str], None] = print,
          channels_path: str = CHANNELS_JSON_PATH) -> Dict[str, Any]:
    ch = _channel(query, channels_path)
    if not ch or not ch.get("frequency"):
        raise ValueError(f"No channel matches {query!r}. See: yagi list")
    freq = int(ch["frequency"])
    name = f"{ch.get('channel_number', '')} {ch.get('display_name') or ch.get('name') or ''}".strip()
    seconds = max(int(INTERVAL_SEC), min(MAX_SECONDS, int(seconds)))

    live = _live_source(freq)
    if live:
        adapter, path = live
        say(f"{name}: reading live TV on tuner {adapter} for {seconds} s. Ctrl+C stops.")
        result = _watch(adapter, _follow(path), seconds, say)
    else:
        from engine.tuner import TunerManager

        adapter = pool.pick_work(wait_for_guide=False)
        if adapter is None:
            raise RuntimeError(pool.busy_text())
        with state_lock(pool.lock_key(adapter), timeout=0.5):
            if pool.claims().get(adapter) or not TunerManager.adapter_is_free(adapter):
                raise RuntimeError(pool.busy_text())
            conf = get_runtime_socket("yagi-signal.conf")
            with open(conf, "w", encoding="utf-8") as f:
                f.write(f"[CHECK]\n\tDELIVERY_SYSTEM = ATSC\n\tFREQUENCY = {freq}\n\tMODULATION = VSB/8\n")
            proc = subprocess.Popen(["dvbv5-zap", "-a", str(adapter), "-c", conf, "-P", "-o", "-", "CHECK"],
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            try:
                say(f"{name}: tuner {adapter} for {seconds} s. Ctrl+C stops.")
                result = _watch(adapter, _pipe(proc), seconds, say)
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                try:
                    os.remove(conf)
                except OSError:
                    pass

    snr = result["snr"]
    if snr:
        say(f"C/N {statistics.mean(snr):.1f} dB average ({min(snr):.1f}–{max(snr):.1f}). 8VSB breaks up near 15.")
    pct = 100.0 * result["damaged"] / result["packets"] if result["packets"] else 0.0
    say(f"{result['damaged_windows']} of {result['windows']} readings damaged, "
        f"{result['damaged']:,} damaged packets ({pct:.3f}%). {verdict(result['windows'], result['damaged_windows'])}")
    return dict(result, channel=name, adapter=adapter, live=bool(live))
