"""The tuners, one pool. Live TV, recordings, scans, and the Guide take whichever is free.

Live TV prefers the lowest tuner and work the highest, so with two and nothing
else going on the old split holds. One tuner does one job at a time. A Guide
update is the only job that gives way: live TV takes its tuner at once, a
recording between towers.
"""

import glob
import json
import os
import time
from typing import Dict, List, Optional, Tuple

from engine.paths import GUIDE_STATUS_PATH, SCAN_STATUS_PATH, get_runtime_socket

DVB_ROOT = "/dev/dvb"
SCAN_HEARTBEAT_SECS = 15
YIELD_PATH = get_runtime_socket("omarchy-tv-guide-yield")
YIELD_FRESH_SECS = 30


LOCK_PREFIX = "tuner"


def lock_key(adapter_id: int) -> str:
    """One process at a time tunes this adapter."""
    return f"{LOCK_PREFIX}{int(adapter_id)}"


class BothTunersBusy(RuntimeError):
    pass


def detect_adapters(root: str = DVB_ROOT) -> Tuple[int, ...]:
    """The tuners this machine has: each adapterN with a frontend."""
    found = []
    for path in glob.glob(os.path.join(root, "adapter*", "frontend0")):
        name = os.path.basename(os.path.dirname(path))
        if name[len("adapter"):].isdigit():
            found.append(int(name[len("adapter"):]))
    return tuple(sorted(found))


def adapters() -> Tuple[int, ...]:
    return detect_adapters()


def busy_text() -> str:
    return "The tuner is busy." if len(adapters()) == 1 else "Both tuners are busy."


def _read_json(path: str) -> Dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def claims(active_path: Optional[str] = None) -> Dict[int, str]:
    """Adapter to the job holding it: live, record, scan, or guide."""
    from engine.dvr import DvrManager
    from engine.timeshift import Timeshift

    out: Dict[int, str] = {}
    guide = _read_json(GUIDE_STATUS_PATH)
    if guide.get("running") and _alive(int(guide.get("pid") or 0)) and guide.get("adapter") is not None:
        out[int(guide["adapter"])] = "guide"
    scan = _read_json(SCAN_STATUS_PATH)
    if scan.get("is_scanning") and time.time() - float(scan.get("updated_at") or 0) < SCAN_HEARTBEAT_SECS:
        out[int(scan.get("adapter_id") if scan.get("adapter_id") is not None else 1)] = "scan"
    live = Timeshift.load_state()
    if live.get("running") and _alive(int(live.get("pid") or 0)):
        out[int(live.get("adapter_id") or 0)] = "live"
    for session in DvrManager.load_active_sessions(active_path):
        if session.is_active():
            # A copy of the live dump shares live TV's tuner; that tuner stays "live".
            out.setdefault(int(session.adapter_id), "record")
    return out


def live_adapter() -> Optional[int]:
    """The tuner the live picture is on, or None with the TV closed."""
    return next((a for a, job in claims().items() if job == "live"), None)


def pick_live(held: Optional[Dict[int, str]] = None) -> int:
    """The tuner live TV should use. Raises BothTunersBusy when nothing can give way."""
    held = claims() if held is None else held
    order = adapters()
    for adapter in order:
        if held.get(adapter) == "live":
            return adapter
    for adapter in order:
        if adapter not in held:
            return adapter
    for adapter in order:
        if held.get(adapter) == "guide":
            return adapter
    raise BothTunersBusy(f"{busy_text()} Stop a recording to watch.")


def pick_work(held: Optional[Dict[int, str]] = None, wait_for_guide: bool = True) -> Optional[int]:
    """A tuner for a recording, scan, or Guide update, or None.

    With wait_for_guide, a tuner the Guide holds counts; the caller waits for its
    tower under lock_key.
    """
    held = claims() if held is None else held
    order = tuple(reversed(adapters()))
    for adapter in order:
        if adapter not in held:
            return adapter
    if wait_for_guide:
        for adapter in order:
            if held.get(adapter) == "guide":
                return adapter
    return None


def free_count(held: Optional[Dict[int, str]] = None) -> int:
    held = claims() if held is None else held
    return sum(1 for a in adapters() if a not in held)


def ask_guide_to_yield(adapter_id: int) -> None:
    tmp = f"{YIELD_PATH}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"adapter": int(adapter_id), "at": time.time()}, f)
    os.replace(tmp, YIELD_PATH)


def guide_must_yield(adapter_id: int) -> bool:
    data = _read_json(YIELD_PATH)
    return (
        data.get("adapter") is not None
        and int(data["adapter"]) == int(adapter_id)
        and time.time() - float(data.get("at") or 0) < YIELD_FRESH_SECS
    )


def clear_yield() -> None:
    try:
        os.remove(YIELD_PATH)
    except OSError:
        pass


def describe(held: Optional[Dict[int, str]] = None) -> List[str]:
    held = claims() if held is None else held
    return [f"Tuner {a}: {held.get(a, 'free')}" for a in adapters()]
