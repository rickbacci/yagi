"""Shows waiting to record. A promise until the start time, then Tuner 1."""

import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

from engine.paths import SCHEDULE_PATH, chmod_private_file, ensure_private_dir, state_lock
from engine.psip import GPS_LEAP_SECONDS, GPS_UNIX_OFFSET

# A minute early, three minutes late. A game adds extra_end_sec on its own row.
PAD_EARLY_SEC = 60
PAD_LATE_SEC = 180


def unix_from_gps(gps_start: Any) -> int:
    try:
        gps = int(gps_start)
    except (TypeError, ValueError):
        return 0
    if gps <= 0:
        return 0
    return gps + GPS_UNIX_OFFSET - GPS_LEAP_SECONDS


def load_schedule(path: Optional[str] = None) -> List[Dict[str, Any]]:
    target = path or SCHEDULE_PATH
    try:
        with open(target, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def save_schedule(items: List[Dict[str, Any]], path: Optional[str] = None) -> None:
    target = path or SCHEDULE_PATH
    ensure_private_dir(os.path.dirname(target))
    tmp = f"{target}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"items": items}, f, indent=2)
    os.replace(tmp, target)
    chmod_private_file(target)


def _pad(row: Dict[str, Any], key: str, default: int) -> int:
    raw = row.get(key)
    if raw is None or raw == "":
        return default
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return default


def item_window(row: Dict[str, Any]) -> Tuple[int, int]:
    """Unix times when this row may start and when it must stop."""
    start = int(row.get("start_unix") or 0)
    duration = max(60, int(row.get("duration_sec") or 0))
    early = _pad(row, "pad_early_sec", PAD_EARLY_SEC)
    late = _pad(row, "pad_late_sec", PAD_LATE_SEC)
    extra = _pad(row, "extra_end_sec", 0)
    return start - early, start + duration + late + extra


def add_later(
    tune_name: str,
    title: str,
    gps_start: Any,
    duration_sec: int,
    clock: str = "",
    end_clock: str = "",
    display_name: str = "",
    extra_end_sec: int = 0,
    slot_id: str = "",
    path: Optional[str] = None,
) -> Dict[str, Any]:
    tune = (tune_name or "").strip()
    name = (title or "").strip() or "Scheduled"
    start = unix_from_gps(gps_start)
    if not tune or start <= 0:
        raise ValueError("A station and a start time are required.")
    try:
        gps = int(gps_start)
    except (TypeError, ValueError):
        gps = 0
    item = {
        "id": f"{tune}-{gps}",
        "tune_name": tune,
        "title": name,
        "display_name": display_name or tune,
        "clock": clock,
        "end_clock": end_clock,
        "gps_start": gps,
        "start_unix": start,
        "duration_sec": max(60, int(duration_sec or 0)),
        "pad_early_sec": PAD_EARLY_SEC,
        "pad_late_sec": PAD_LATE_SEC,
        "extra_end_sec": max(0, int(extra_end_sec or 0)),
        "slot_id": str(slot_id or ""),
        "status": "waiting",
    }
    with state_lock(path or SCHEDULE_PATH):
        items = [row for row in load_schedule(path) if row.get("id") != item["id"]]
        items.append(item)
        items.sort(key=lambda row: int(row.get("start_unix") or 0))
        save_schedule(items, path)
    return item


def remove_later(item_id: str, path: Optional[str] = None) -> bool:
    ident = (item_id or "").strip()
    with state_lock(path or SCHEDULE_PATH):
        items = load_schedule(path)
        kept = [row for row in items if str(row.get("id") or "") != ident]
        if len(kept) == len(items):
            return False
        save_schedule(kept, path)
    return True


def due_items(now: Optional[float] = None, path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Rows inside their record window. A window that closed without a start is missed."""
    stamp = time.time() if now is None else float(now)
    ready = []
    with state_lock(path or SCHEDULE_PATH):
        items = load_schedule(path)
        changed = False
        for row in items:
            if str(row.get("status") or "waiting") == "missed":
                continue
            start = int(row.get("start_unix") or 0)
            if start <= 0:
                continue
            arm, end = item_window(row)
            if stamp >= end:
                row["status"] = "missed"
                changed = True
                continue
            if arm <= stamp:
                ready.append(row)
        if changed:
            save_schedule(items, path)
    return ready


def pick_due(ready: List[Dict[str, Any]], tuner_busy: bool) -> Optional[Dict[str, Any]]:
    """Tuner 1 records one show. The rest stay listed."""
    if tuner_busy or not ready:
        return None
    return ready[0]


def drop_item(item_id: str, path: Optional[str] = None) -> None:
    remove_later(item_id, path)
