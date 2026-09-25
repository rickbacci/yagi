"""
Omarchy TV - Electronic Program Guide (EPG) Engine
Manages schedule data, program synopses, and airings in guide.json.
Provides current and upcoming show information for major broadcast stations.
"""

import os
import json
import re
import time
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List, Callable, Tuple
from zoneinfo import ZoneInfo

from engine.paths import (
    CHANNELS_JSON_PATH,
    GUIDE_HISTORY_PATH,
    GUIDE_JSON_PATH,
    chmod_private_file,
    ensure_private_dir,
)

_EASTERN = ZoneInfo("America/New_York")


EVENING_SLOTS = [
    "6:00 PM", "6:30 PM", "7:00 PM", "7:30 PM",
    "8:00 PM", "8:30 PM", "9:00 PM", "9:30 PM",
    "10:00 PM", "10:30 PM",
]


def _write_guide(payload: Dict[str, Any], target: str) -> None:
    ensure_private_dir(os.path.dirname(target))
    tmp = f"{target}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, target)
    chmod_private_file(target)


_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})\s*(AM|PM)$", re.IGNORECASE)


def parse_minutes(label: str) -> int:
    m = _TIME_RE.match(str(label or "").strip())
    if not m:
        return -1
    hour = int(m.group(1))
    minute = int(m.group(2))
    if hour == 12:
        hour = 0
    if m.group(3).upper() == "PM":
        hour += 12
    return hour * 60 + minute


def _now_minutes() -> int:
    local = time.localtime()
    return local.tm_hour * 60 + local.tm_min


def _program_span(prog: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    """Unix start and end when the airing has a GPS time. Clock text is not a date."""
    from engine.psip import GPS_LEAP_SECONDS, GPS_UNIX_OFFSET

    raw = prog.get("gps_start")
    if raw is None or raw == "":
        return None
    try:
        gps = int(raw)
    except (TypeError, ValueError):
        return None
    if gps <= 0:
        return None
    start = gps + GPS_UNIX_OFFSET - GPS_LEAP_SECONDS
    try:
        dur = int(prog.get("duration_sec") or 0)
    except (TypeError, ValueError):
        dur = 0
    if dur <= 0:
        dur = 30 * 60
    return start, start + dur


def _clock_covers(prog: Dict[str, Any], clock: int) -> bool:
    start = parse_minutes(str(prog.get("start") or prog.get("start_time") or ""))
    end = parse_minutes(str(prog.get("end") or prog.get("end_time") or ""))
    if start < 0:
        return False
    when = clock
    if end < 0:
        end = start + 30
    if end <= start:
        end += 24 * 60
        if when < start:
            when += 24 * 60
    return start <= when < end


def now_and_next(
    programs: Optional[List[Dict[str, Any]]],
    now_minutes: Optional[int] = None,
    now_unix: Optional[float] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Program covering now, then the following block.

    An airing with gps_start matches that instant. The clock is only for a
    block that has no date, so yesterday's 8:15 PM does not cover tonight.
    """
    rows = [p for p in (programs or []) if isinstance(p, dict)]
    if not rows:
        return None, None
    stamp = time.time() if now_unix is None else float(now_unix)
    clock = _now_minutes() if now_minutes is None else int(now_minutes)
    spans = [_program_span(prog) for prog in rows]
    covering_idx = None
    if any(spans):
        for i, span in enumerate(spans):
            if span is not None and span[0] <= stamp < span[1]:
                covering_idx = i
                break
    else:
        for i, prog in enumerate(rows):
            if _clock_covers(prog, clock):
                covering_idx = i
                break
    if covering_idx is None:
        return None, None
    nxt = rows[covering_idx + 1] if covering_idx + 1 < len(rows) else None
    return rows[covering_idx], nxt


def program_is_on(
    program: Optional[Dict[str, Any]],
    now_minutes: Optional[int] = None,
    now_unix: Optional[float] = None,
) -> bool:
    """True when this program block covers now."""
    covering, _ = now_and_next(
        [program] if isinstance(program, dict) else [],
        now_minutes,
        now_unix=now_unix,
    )
    return covering is not None


def remaining_record_minutes(
    program: Optional[Dict[str, Any]],
    now_minutes: Optional[int] = None,
    now_unix: Optional[float] = None,
) -> Optional[int]:
    """Minutes from now (or the start, if later) until this block ends."""
    if not isinstance(program, dict):
        return None
    span = _program_span(program)
    if span is not None:
        stamp = time.time() if now_unix is None else float(now_unix)
        start, end = span
        if stamp >= end:
            return None
        if stamp < start:
            return max(1, int(round((end - start) / 60)))
        return max(1, int(round((end - stamp) / 60)))
    clock = _now_minutes() if now_minutes is None else int(now_minutes)
    start = parse_minutes(str(program.get("start") or program.get("start_time") or ""))
    end = parse_minutes(str(program.get("end") or program.get("end_time") or ""))
    if start < 0:
        sec = program.get("duration_sec")
        if sec:
            return max(1, int(round(int(sec) / 60)))
        return None
    if end < 0:
        end = start + 30
    when = clock
    if end <= start:
        end += 24 * 60
        if when < start:
            when += 24 * 60
    remain = end - max(when, start)
    if remain <= 0:
        return None
    return int(remain)


FILLER_TITLES = {"paid programming", "paid program", "programa pagado", "to be announced"}


def collapse_repeats(text: str) -> str:
    """One copy of a text an older parser glued to itself."""
    n = len(text)
    for period in range(20, n // 2 + 1):
        chunk = text[:period]
        if text.startswith(chunk * 2) and (chunk * (n // period + 1)).startswith(text):
            return chunk.strip()
    return text


def is_filler_title(title: Any) -> bool:
    """Infomercials and placeholders. Kept in guide.json, left out of the guide."""
    return str(title or "").strip().lower() in FILLER_TITLES


def search_guide(
    channels: Optional[Dict[str, Any]],
    query: str,
    now_minutes: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Title matches, each with the show before and after on that channel."""
    words = [w for w in str(query or "").lower().split() if w]
    if len(" ".join(words)) < 2:
        return []
    hits: List[Dict[str, Any]] = []
    for number, row in (channels or {}).items():
        if not isinstance(row, dict):
            continue
        programs = [p for p in (row.get("programs") or []) if isinstance(p, dict)]
        for index, prog in enumerate(programs):
            title = str(prog.get("title") or "")
            folded = title.lower()
            if not title or is_filler_title(title) or not all(word in folded for word in words):
                continue
            when = _program_when(prog)
            hits.append({
                "_sort": (0, when.timestamp()) if when else (1, parse_minutes(str(prog.get("start") or ""))),
                "channel_number": str(number),
                "callsign": row.get("callsign") or row.get("station") or "",
                "tune_name": row.get("tune_name") or "",
                "title": title,
                "start": prog.get("start") or "",
                "end": prog.get("end") or "",
                "synopsis": prog.get("synopsis") or "",
                "usual": prog.get("usual") or "",
                "also": prog.get("also") or "",
                "duration_sec": int(prog.get("duration_sec") or 0),
                "on_now": program_is_on(prog, now_minutes),
                "before": _neighbor_program(programs[index - 1] if index else None),
                "after": _neighbor_program(programs[index + 1] if index + 1 < len(programs) else None),
            })
    hits.sort(key=lambda hit: (hit["_sort"], _channel_sort_key(hit.get("channel_number"))))
    for hit in hits:
        del hit["_sort"]
    return hits


def _neighbor_program(prog: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    if not isinstance(prog, dict) or not prog.get("title"):
        return None
    return {
        "title": str(prog.get("title") or ""),
        "start": str(prog.get("start") or ""),
        "end": str(prog.get("end") or ""),
    }


def _channel_sort_key(number: Any) -> float:
    try:
        return float(number)
    except (TypeError, ValueError):
        return 999.0


def format_guide_updated(updated_at: Optional[float], now: Optional[float] = None) -> str:
    """Clock label for when the saved listings were written."""
    if not updated_at:
        return "Listings have not been updated."
    when = datetime.fromtimestamp(float(updated_at))
    current = datetime.fromtimestamp(now) if now is not None else datetime.now()
    clock = when.strftime("%-I:%M %p")
    if when.date() == current.date():
        return f"Updated {clock}"
    return f"Updated {when.strftime('%b')} {when.day}, {clock}"


def current_program_title(
    channel_row: Optional[Dict[str, Any]],
    now_minutes: Optional[int] = None,
) -> str:
    """Title of the block on now, not a stale channel-level leftover."""
    if not isinstance(channel_row, dict):
        return "Live Broadcast"
    programs = channel_row.get("programs")
    now_prog, _ = now_and_next(programs, now_minutes)
    if now_prog:
        title = str(now_prog.get("title") or "").strip()
        return title or "Live Broadcast"
    if any(_program_span(prog) for prog in (programs or []) if isinstance(prog, dict)):
        return "Live Broadcast"
    title = str(channel_row.get("title") or "").strip()
    return title or "Live Broadcast"


def _channel_number(channel: Dict[str, Any]) -> str:
    number = channel.get("channel_number")
    if number:
        return str(number)
    major = channel.get("major")
    minor = channel.get("minor")
    if major is not None and minor is not None:
        return f"{major}.{minor}"
    return ""


def _row_from_scan(channel: Dict[str, Any], prior: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    prior = prior if isinstance(prior, dict) else {}
    if prior.get("source") == "psip":
        programs = list(prior.get("programs") or [])
    elif prior.get("programs"):
        programs = list(prior.get("programs"))
    else:
        programs = []
    now_prog, next_prog = now_and_next(programs)
    dated = any(_program_span(prog) for prog in programs if isinstance(prog, dict))
    if now_prog:
        title = now_prog.get("title") or "Live"
        start = now_prog.get("start") or ""
        end = now_prog.get("end") or ""
        next_title = (next_prog or {}).get("title") or ""
    elif dated:
        title, start, end, next_title = "Live", "", "", ""
    else:
        title = prior.get("title") or "Live"
        start = prior.get("start_time") or ""
        end = prior.get("end_time") or ""
        next_title = prior.get("next_title") or ""
    return {
        "network": channel.get("network") or prior.get("network") or "",
        "station": channel.get("callsign") or prior.get("station") or "",
        "tune_name": channel.get("tune_name") or channel.get("name") or prior.get("tune_name") or "",
        "callsign": channel.get("callsign") or prior.get("callsign") or "",
        "display_name": channel.get("display_name") or channel.get("name") or prior.get("display_name") or "",
        "programs": list(programs),
        "is_translator": bool(channel.get("is_translator") or prior.get("is_translator")),
        "source": prior.get("source") or "",
        "title": title,
        "start_time": start,
        "end_time": end,
        "next_title": next_title,
        "synopsis": prior.get("synopsis") or "",
    }


def merge_lineup(
    channels: Optional[List[Dict[str, Any]]],
    existing: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Guide rows keyed by virtual channel, one per scanned station."""
    existing = existing if isinstance(existing, dict) else {}
    merged: Dict[str, Any] = {}
    for channel in channels or []:
        if not isinstance(channel, dict):
            continue
        number = _channel_number(channel)
        if not number:
            continue
        merged[number] = _row_from_scan(channel, existing.get(number))
    return merged


def apply_program_events(channels: Dict[str, Any], events: Dict[str, List[Dict[str, Any]]]) -> None:
    for number, programs in (events or {}).items():
        if number not in channels or not isinstance(programs, list):
            continue
        channels[number]["programs"] = [p for p in programs if isinstance(p, dict)]
        channels[number]["source"] = "psip"
        now_prog, next_prog = now_and_next(channels[number]["programs"])
        if now_prog:
            channels[number]["title"] = now_prog.get("title") or channels[number].get("title")
            channels[number]["start_time"] = now_prog.get("start") or ""
            channels[number]["end_time"] = now_prog.get("end") or ""
            channels[number]["synopsis"] = now_prog.get("synopsis") or ""
        elif any(_program_span(prog) for prog in channels[number]["programs"]):
            channels[number]["title"] = "Live"
            channels[number]["start_time"] = ""
            channels[number]["end_time"] = ""
            channels[number]["synopsis"] = ""
        if next_prog:
            channels[number]["next_title"] = next_prog.get("title") or ""
        elif not now_prog:
            channels[number]["next_title"] = ""


def epg_tuner_held(sessions: Optional[List[Any]] = None) -> bool:
    """Tuner 1 is the EPG/record tuner. A live recording holds it."""
    if sessions is None:
        from engine.dvr import DvrManager
        sessions = DvrManager.load_active_sessions()
    for session in sessions or []:
        is_active = getattr(session, "is_active", None)
        if callable(is_active):
            if is_active():
                return True
        elif session:
            return True
    return False


def _read_channels_file(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, dict) and isinstance(data.get("channels"), list):
        return [ch for ch in data["channels"] if isinstance(ch, dict)]
    if isinstance(data, list):
        return [ch for ch in data if isinstance(ch, dict)]
    return []


_WEEKDAY_NAMES = (
    "Mondays",
    "Tuesdays",
    "Wednesdays",
    "Thursdays",
    "Fridays",
    "Saturdays",
    "Sundays",
)
_HISTORY_RAW_SEC = 28 * 24 * 3600
_HISTORY_USUAL_SEC = 120 * 24 * 3600
# Most stations send about five hours ahead. Three hours leaves no gap.
GUIDE_GRAB_GAP_SEC = 3 * 3600
# Sixteen towers at about half a minute each, with room to spare.
GUIDE_GRAB_RUN_SEC = 10 * 60


def _fold_title(title: str) -> str:
    """Case, spaces, and punctuation, so MASH and M*A*S*H are one name."""
    chars = []
    for ch in str(title or "").casefold():
        if ch.isalnum():
            chars.append(ch)
        elif ch.isspace():
            chars.append(" ")
    return " ".join("".join(chars).split())


def _slot_names(slot: Dict[str, Any]) -> set:
    names = {_fold_title(str(slot.get("title") or ""))}
    for alias in slot.get("aliases") or []:
        folded = _fold_title(str(alias))
        if folded:
            names.add(folded)
    names.discard("")
    return names


def _airing_duration(prog: Dict[str, Any]) -> int:
    """Seconds the airing ran. Clock end wins over a missing duration."""
    try:
        dur = int(prog.get("duration_sec") or 0)
    except (TypeError, ValueError):
        dur = 0
    if dur > 0:
        return dur
    start = parse_minutes(str(prog.get("start") or prog.get("start_time") or ""))
    end = parse_minutes(str(prog.get("end") or prog.get("end_time") or ""))
    if start < 0 or end < 0:
        return 0
    if end <= start:
        end += 24 * 60
    return (end - start) * 60


def _program_when(prog: Dict[str, Any]) -> Optional[datetime]:
    gps = prog.get("gps_start")
    if gps is None or gps == "":
        return None
    try:
        gps_i = int(gps)
    except (TypeError, ValueError):
        return None
    from engine.psip import gps_to_datetime

    return gps_to_datetime(gps_i)


def _load_history(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {"airings": [], "usual": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"airings": [], "usual": []}
    if not isinstance(data, dict):
        return {"airings": [], "usual": []}
    airings = data.get("airings") if isinstance(data.get("airings"), list) else []
    usual = data.get("usual") if isinstance(data.get("usual"), list) else []
    return {"airings": airings, "usual": usual}


def _save_history(payload: Dict[str, Any], path: str) -> None:
    ensure_private_dir(os.path.dirname(path))
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, path)
    chmod_private_file(path)


def _usual_line(slot: Dict[str, Any]) -> str:
    weeks = slot.get("weeks") or []
    if len(weeks) < 2:
        return ""
    weekday = int(slot.get("weekday") or 0)
    if weekday < 0 or weekday > 6:
        return ""
    clock = str(slot.get("clock") or "")
    if not clock:
        return ""
    return f"Usually {_WEEKDAY_NAMES[weekday]} at {clock}"


def remember_guide_history(
    channels: Optional[Dict[str, Any]],
    history_path: Optional[str] = None,
    now: Optional[float] = None,
) -> Dict[str, Any]:
    """Keep about a month of real airings, and the weekly slot after it repeats."""
    path = history_path or GUIDE_HISTORY_PATH
    now_ts = time.time() if now is None else float(now)
    history = _load_history(path)
    fresh: List[Dict[str, Any]] = []
    for number, row in (channels or {}).items():
        if not isinstance(row, dict):
            continue
        programs = [p for p in (row.get("programs") or []) if isinstance(p, dict)]
        for index, prog in enumerate(programs):
            when = _program_when(prog)
            title = str(prog.get("title") or "").strip()
            clock = str(prog.get("start") or "").strip()
            if when is None or not title or not clock:
                continue
            before = programs[index - 1] if index else None
            after = programs[index + 1] if index + 1 < len(programs) else None
            fresh.append({
                "channel": str(number),
                "station": str(row.get("station") or row.get("callsign") or ""),
                "title": title,
                "start": int(when.timestamp()),
                "duration_sec": _airing_duration(prog),
                "weekday": when.weekday(),
                "clock": clock,
                "before": str((before or {}).get("title") or ""),
                "after": str((after or {}).get("title") or ""),
            })

    seen = {
        (str(item.get("channel")), _fold_title(str(item.get("title") or "")), int(item.get("start") or 0))
        for item in history["airings"]
        if isinstance(item, dict)
    }
    for item in fresh:
        key = (item["channel"], _fold_title(item["title"]), item["start"])
        if key in seen:
            continue
        history["airings"].append(item)
        seen.add(key)

    raw_cut = now_ts - _HISTORY_RAW_SEC
    history["airings"] = [
        item for item in history["airings"]
        if isinstance(item, dict) and int(item.get("start") or 0) >= raw_cut
    ]

    slots: Dict[Tuple[str, str, int, str], Dict[str, Any]] = {}
    kept_usual: List[Dict[str, Any]] = []
    for slot in history["usual"]:
        if not isinstance(slot, dict):
            continue
        key = (
            str(slot.get("channel") or ""),
            _fold_title(str(slot.get("title") or "")),
            int(slot.get("weekday") or 0),
            str(slot.get("clock") or ""),
        )
        slots[key] = slot
        kept_usual.append(slot)
    history["usual"] = kept_usual
    for item in fresh:
        when = datetime.fromtimestamp(item["start"], tz=_EASTERN)
        iso = when.isocalendar()
        week = f"{iso.year}-W{iso.week:02d}"
        folded = _fold_title(item["title"])
        key = (item["channel"], folded, item["weekday"], item["clock"])
        slot = slots.get(key)
        if slot is None:
            for existing in history["usual"]:
                if (
                    str(existing.get("channel") or "") == item["channel"]
                    and int(existing.get("weekday") or 0) == item["weekday"]
                    and str(existing.get("clock") or "") == item["clock"]
                    and folded in _slot_names(existing)
                ):
                    slot = existing
                    break
        if slot is None:
            slot = {
                "id": uuid.uuid4().hex[:12],
                "channel": item["channel"],
                "tune_name": item.get("station") or item["channel"],
                "title": item["title"],
                "weekday": item["weekday"],
                "clock": item["clock"],
                "duration_sec": int(item.get("duration_sec") or 0),
                "aliases": [],
                "weeks": [],
                "last_start": item["start"],
            }
            history["usual"].append(slot)
            slots[key] = slot
        elif key not in slots:
            slots[key] = slot
        weeks = slot.setdefault("weeks", [])
        if week not in weeks:
            weeks.append(week)
        if not slot.get("title_locked"):
            slot["title"] = item["title"]
        slot["last_start"] = max(int(slot.get("last_start") or 0), item["start"])
        learned = int(item.get("duration_sec") or 0)
        if learned > 0 and not slot.get("length_locked"):
            slot["duration_sec"] = learned

    usual_cut = now_ts - _HISTORY_USUAL_SEC
    history["usual"] = [
        slot for slot in history["usual"]
        if isinstance(slot, dict) and int(slot.get("last_start") or 0) >= usual_cut
    ]
    slots = {
        (
            str(slot.get("channel") or ""),
            _fold_title(str(slot.get("title") or "")),
            int(slot.get("weekday") or 0),
            str(slot.get("clock") or ""),
        ): slot
        for slot in history["usual"]
    }

    for number, row in (channels or {}).items():
        if not isinstance(row, dict):
            continue
        for prog in row.get("programs") or []:
            if not isinstance(prog, dict):
                continue
            when = _program_when(prog)
            clock = str(prog.get("start") or "").strip()
            title = str(prog.get("title") or "").strip()
            if when is None or not clock or not title:
                continue
            slot = slots.get((str(number), _fold_title(title), when.weekday(), clock))
            line = _usual_line(slot) if slot else ""
            if line:
                prog["usual"] = line

    for slot in history["usual"]:
        if isinstance(slot, dict) and not slot.get("id"):
            slot["id"] = uuid.uuid4().hex[:12]
    _save_history({"airings": history["airings"], "usual": history["usual"]}, path)
    return history


def delete_airing(
    channel: str,
    start: int,
    history_path: Optional[str] = None,
) -> bool:
    """Drop one remembered airing. The rest of the log stays as it was."""
    path = history_path or GUIDE_HISTORY_PATH
    history = _load_history(path)
    ident = (str(channel or "").strip(), int(start))
    kept = [
        item for item in history["airings"]
        if not (
            isinstance(item, dict)
            and (str(item.get("channel") or ""), int(item.get("start") or 0)) == ident
        )
    ]
    if len(kept) == len(history["airings"]):
        return False
    history["airings"] = kept
    _save_history(history, path)
    return True


def guide_grab_due(
    now: float,
    updated_at: Any,
    tuner_busy: bool,
    gap: int = GUIDE_GRAB_GAP_SEC,
    next_record_at: Optional[float] = None,
) -> bool:
    """Every few hours, only when Tuner 1 is free, and not when a recording would have to wait."""
    if tuner_busy:
        return False
    if next_record_at is not None and float(next_record_at) - float(now) < GUIDE_GRAB_RUN_SEC:
        return False
    try:
        updated = float(updated_at or 0)
    except (TypeError, ValueError):
        updated = 0.0
    if updated <= 0:
        return True
    return float(now) - updated >= gap


def listed_slots(history: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Repeated shows, plus any slot you added or marked to record."""
    out = []
    for slot in history.get("usual") or []:
        if not isinstance(slot, dict):
            continue
        weeks = slot.get("weeks") or []
        if len(weeks) >= 2 or slot.get("manual") or slot.get("record"):
            out.append(slot)
    out.sort(key=lambda slot: (int(slot.get("weekday") or 0), str(slot.get("clock") or ""), str(slot.get("title") or "")))
    return out


def _edit_slot(slot_id: str, path: str, change) -> Optional[Dict[str, Any]]:
    history = _load_history(path)
    ident = (slot_id or "").strip()
    for slot in history["usual"]:
        if isinstance(slot, dict) and str(slot.get("id") or "") == ident:
            change(slot)
            _save_history(history, path)
            return slot
    return None


def add_slot(
    channel: str,
    title: str,
    weekday: int,
    clock: str,
    duration_sec: int,
    tune_name: str = "",
    history_path: Optional[str] = None,
) -> Dict[str, Any]:
    path = history_path or GUIDE_HISTORY_PATH
    name = (title or "").strip()
    when = (clock or "").strip()
    if not (channel or "").strip() or not name or not when:
        raise ValueError("A station, a title, and a clock are required.")
    if parse_minutes(when) < 0:
        raise ValueError("Clock looks like 8:15 PM.")
    if int(weekday) < 0 or int(weekday) > 6:
        raise ValueError("Weekday is 0 for Monday through 6 for Sunday.")
    history = _load_history(path)
    slot = {
        "id": uuid.uuid4().hex[:12],
        "channel": str(channel).strip(),
        "tune_name": (tune_name or channel).strip(),
        "title": name,
        "title_locked": True,
        "weekday": int(weekday),
        "clock": when,
        "duration_sec": max(60, int(duration_sec or 0)),
        "length_locked": True,
        "aliases": [],
        "weeks": [],
        "manual": True,
        "last_start": int(time.time()),
    }
    history["usual"].append(slot)
    _save_history(history, path)
    return slot


def rename_slot(slot_id: str, title: str, history_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    name = (title or "").strip()
    if not name:
        raise ValueError("A title is required.")

    def change(slot):
        slot["title"] = name
        slot["title_locked"] = True

    return _edit_slot(slot_id, history_path or GUIDE_HISTORY_PATH, change)


def set_slot_clock(slot_id: str, clock: str, history_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    when = (clock or "").strip()
    if parse_minutes(when) < 0:
        raise ValueError("Clock looks like 8:15 PM.")

    def change(slot):
        slot["clock"] = when

    return _edit_slot(slot_id, history_path or GUIDE_HISTORY_PATH, change)


def set_slot_length(slot_id: str, duration_sec: int, history_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    length = max(60, int(duration_sec or 0))

    def change(slot):
        slot["duration_sec"] = length
        slot["length_locked"] = True

    return _edit_slot(slot_id, history_path or GUIDE_HISTORY_PATH, change)


def delete_slot(slot_id: str, history_path: Optional[str] = None) -> bool:
    path = history_path or GUIDE_HISTORY_PATH
    history = _load_history(path)
    ident = (slot_id or "").strip()
    kept = [slot for slot in history["usual"] if str(slot.get("id") or "") != ident]
    if len(kept) == len(history["usual"]):
        return False
    history["usual"] = kept
    _save_history(history, path)
    return True


def set_slot_aliases(slot_id: str, aliases: List[str], history_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    names = []
    for alias in aliases:
        text = str(alias or "").strip()
        if text and text not in names:
            names.append(text)

    def change(slot):
        slot["aliases"] = names

    return _edit_slot(slot_id, history_path or GUIDE_HISTORY_PATH, change)


def set_slot_record(slot_id: str, record: bool, history_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    def change(slot):
        slot["record"] = bool(record)

    return _edit_slot(slot_id, history_path or GUIDE_HISTORY_PATH, change)


def arm_weekly_slots(
    now: Optional[float] = None,
    history_path: Optional[str] = None,
    schedule_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Queue this week's airing for every slot marked to record. A miss keeps the mark."""
    from engine.psip import GPS_LEAP_SECONDS, GPS_UNIX_OFFSET
    from engine.schedule import add_later, load_schedule

    stamp = time.time() if now is None else float(now)
    local = datetime.fromtimestamp(stamp, tz=_EASTERN)
    history = _load_history(history_path or GUIDE_HISTORY_PATH)
    queued = load_schedule(schedule_path)
    added = []
    for slot in history.get("usual") or []:
        if not isinstance(slot, dict) or not slot.get("record"):
            continue
        if int(slot.get("weekday") or 0) != local.weekday():
            continue
        minutes = parse_minutes(str(slot.get("clock") or ""))
        if minutes < 0:
            continue
        start = local.replace(hour=minutes // 60, minute=minutes % 60, second=0, microsecond=0)
        start_unix = int(start.timestamp())
        duration = max(60, int(slot.get("duration_sec") or 0))
        if stamp < start_unix - 60 or stamp >= start_unix + duration + 180:
            continue
        slot_id = str(slot.get("id") or "")
        if any(
            str(row.get("slot_id") or "") == slot_id and int(row.get("start_unix") or 0) == start_unix
            for row in queued
        ):
            continue
        gps = start_unix - GPS_UNIX_OFFSET + GPS_LEAP_SECONDS
        item = add_later(
            str(slot.get("tune_name") or slot.get("channel") or ""),
            str(slot.get("title") or "Scheduled"),
            gps,
            duration,
            clock=str(slot.get("clock") or ""),
            display_name=str(slot.get("tune_name") or slot.get("channel") or ""),
            slot_id=slot_id,
            path=schedule_path,
        )
        queued.append(item)
        added.append(item)
    return added


def refresh_guide(
    channels: Optional[List[Dict[str, Any]]] = None,
    guide_path: Optional[str] = None,
    channels_path: Optional[str] = None,
    grabber: Optional[Callable[[], Dict[str, List[Dict[str, Any]]]]] = None,
    sessions: Optional[List[Any]] = None,
    reread: bool = False,
) -> Dict[str, Any]:
    """
    Write guide.json from the scanned lineup.
    Optional grabber fills programs; it must not run while a recording holds Tuner 1.
    reread marks the listings stale so the next timer tick reads them.
    """
    target = guide_path or GUIDE_JSON_PATH
    lineup = channels
    if lineup is None:
        lineup = _read_channels_file(channels_path or CHANNELS_JSON_PATH)
    existing: Dict[str, Any] = {}
    read_at = 0.0
    if os.path.exists(target):
        try:
            with open(target, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict) and isinstance(loaded.get("channels"), dict):
                existing = loaded["channels"]
                read_at = float(loaded.get("updated_at") or 0)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            existing = {}
    if lineup:
        merged = merge_lineup(lineup, existing)
    else:
        merged = dict(existing) if existing else {}
    skipped = False
    if grabber is not None:
        if epg_tuner_held(sessions):
            skipped = True
        else:
            apply_program_events(merged, grabber() or {})
            read_at = time.time()
    remember_guide_history(
        merged,
        history_path=os.path.join(os.path.dirname(target), "guide_history.json"),
        now=time.time(),
    )
    for row in merged.values():
        for prog in (row.get("programs") or []) if isinstance(row, dict) else []:
            if isinstance(prog, dict) and prog.get("synopsis"):
                prog["synopsis"] = collapse_repeats(str(prog["synopsis"]))
    # updated_at is when the broadcast was last read. A lineup sync is not a read.
    if reread and grabber is None:
        read_at = 0.0
    payload = {"updated_at": read_at, "channels": merged, "source": "lineup"}
    _write_guide(payload, target)
    return {"skipped": skipped, "channels": merged}


def sync_guide_from_channels(channels: List[Dict[str, Any]], guide_path: Optional[str] = None) -> Dict[str, Any]:
    """A new lineup. The listings are re-read on the next timer tick."""
    return refresh_guide(channels=channels, guide_path=guide_path, grabber=None, sessions=[], reread=True)


def load_guide(guide_path: Optional[str] = None) -> Dict[str, Any]:
    """Loads EPG data from guide.json. Missing file is empty channels, not a canned lineup."""
    target = guide_path or GUIDE_JSON_PATH
    if os.path.exists(target):
        try:
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return save_default_guide(target)


def save_default_guide(guide_path: Optional[str] = None) -> Dict[str, Any]:
    """Writes an empty guide.json until a PSIP refresh fills it."""
    target = guide_path or GUIDE_JSON_PATH
    payload = {
        "updated_at": 0,
        "channels": {},
    }
    _write_guide(payload, target)
    return payload


def get_channel_program(channel_identifier: str, guide_data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """
    Returns the current program for a given channel identifier
    (matches channel_number like '3.1' or station callsign like 'WKYC-HD').
    """
    if guide_data is None:
        guide_data = load_guide()

    channels = guide_data.get("channels", {})

    # Check direct channel number (e.g. "3.1")
    if channel_identifier in channels:
        return channels[channel_identifier]

    # Check station name (e.g. "WKYC-HD", "FOX")
    ident_lower = channel_identifier.lower()
    for ch_num, prog in channels.items():
        if prog.get("station", "").lower() == ident_lower:
            return prog
        if prog.get("network", "").lower() == ident_lower:
            return prog

    return None


def match_guide_program(channel: Dict[str, Any], guide_channels: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Matches a scanned/enriched channel dict to an EPG program entry."""
    if not channel or not guide_channels:
        return None

    ch_num = channel.get("channel_number")
    if ch_num and ch_num in guide_channels:
        return guide_channels[ch_num]

    names = []
    for key in ("name", "raw_name", "tune_name", "callsign"):
        ident = " ".join(str(channel.get(key) or "").split()).strip().lower()
        if ident:
            names.append(ident)

    for prog in guide_channels.values():
        station = " ".join(str(prog.get("station") or "").split()).strip().lower()
        if station and station in names:
            return prog
    return None


def get_timeline_grid(guide_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Returns structured timeline grid for UI rendering:
    Slots: ["NOW", "6:30 PM", "7:00 PM", "7:30 PM"]
    Channels: Array of station rows with their schedule blocks.
    """
    if guide_data is None:
        guide_data = load_guide()

    channels_sched = guide_data.get("channels", {})
    slots = list(EVENING_SLOTS)

    grid_rows = []
    for ch_num, info in channels_sched.items():
        row = {
            "channel_number": ch_num,
            "network": info.get("network", "OTA"),
            "station": info.get("station", ch_num),
            "current_title": info.get("title", "Live Broadcast"),
            "next_title": info.get("next_title", "Evening Programming"),
            "time_window": f"{info.get('start_time', '')} - {info.get('end_time', '')}",
            "synopsis": info.get("synopsis", "")
        }
        grid_rows.append(row)

    grid_rows.sort(key=lambda x: float(x["channel_number"]) if x["channel_number"].replace('.', '', 1).isdigit() else 999)
    return {
        "slots": slots,
        "rows": grid_rows
    }


def get_slot_program(channel_info: Dict[str, Any], slot: int) -> Dict[str, str]:
    """Returns the single EPG cell shown for slot 0 (now) or slot 1 (next)."""
    info = channel_info or {}
    if slot <= 0:
        start = info.get("start_time") or ""
        end = info.get("end_time") or ""
        if start and end:
            time_label = f"{start} – {end}"
        else:
            time_label = "Now"
        return {
            "label": "Now Playing",
            "caption": "This half-hour",
            "title": info.get("title") or "Live Broadcast",
            "time_label": time_label,
        }
    end = info.get("end_time") or ""
    return {
        "label": "Up Next",
        "caption": "Following show",
        "title": info.get("next_title") or "Upcoming",
        "time_label": f"From {end}" if end else "Next",
    }

