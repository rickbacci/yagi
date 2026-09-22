"""Shows waiting to record. A promise until the start time, then Tuner 1."""

import json
import os
import time
from typing import Any, Dict, List, Optional

from engine.paths import SCHEDULE_PATH
from engine.psip import GPS_LEAP_SECONDS, GPS_UNIX_OFFSET


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
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = f"{target}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"items": items}, f, indent=2)
    os.replace(tmp, target)


def add_later(
    tune_name: str,
    title: str,
    gps_start: Any,
    duration_sec: int,
    clock: str = "",
    end_clock: str = "",
    display_name: str = "",
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
    }
    items = [row for row in load_schedule(path) if row.get("id") != item["id"]]
    items.append(item)
    items.sort(key=lambda row: int(row.get("start_unix") or 0))
    save_schedule(items, path)
    return item


def remove_later(item_id: str, path: Optional[str] = None) -> bool:
    ident = (item_id or "").strip()
    items = load_schedule(path)
    kept = [row for row in items if str(row.get("id") or "") != ident]
    if len(kept) == len(items):
        return False
    save_schedule(kept, path)
    return True


def due_items(now: Optional[float] = None, path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Shows whose start has arrived and whose end has not."""
    stamp = time.time() if now is None else float(now)
    ready = []
    kept = []
    for row in load_schedule(path):
        start = int(row.get("start_unix") or 0)
        duration = int(row.get("duration_sec") or 0)
        end = start + max(60, duration)
        if start <= 0 or end <= stamp:
            continue
        kept.append(row)
        if start <= stamp:
            ready.append(row)
    if len(kept) != len(load_schedule(path)):
        save_schedule(kept, path)
    return ready


def drop_item(item_id: str, path: Optional[str] = None) -> None:
    remove_later(item_id, path)
