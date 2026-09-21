"""
Omarchy TV - Electronic Program Guide (EPG) Engine
Manages schedule data, program synopses, and airings in guide.json.
Provides current and upcoming show information for major broadcast stations.
"""

import os
import json
import re
import time
from typing import Dict, Any, Optional, List, Callable, Tuple
from engine.paths import GUIDE_JSON_PATH, CHANNELS_JSON_PATH


# High-quality broadcast schedule templates for North American terrestrial networks
BROADCAST_SCHEDULES: Dict[str, Dict[str, Any]] = {
    "3.1": {
        "network": "NBC",
        "station": "WKYC-HD",
        "title": "NBC Nightly News with Lester Holt",
        "start_time": "6:30 PM",
        "end_time": "7:00 PM",
        "synopsis": "Nightly news broadcast providing in-depth coverage of world, national, and political events.",
        "next_title": "Local News at 7:00 PM"
    },
    "5.1": {
        "network": "ABC",
        "station": "WEWSHD",
        "title": "ABC World News Tonight with David Muir",
        "start_time": "6:30 PM",
        "end_time": "7:00 PM",
        "synopsis": "David Muir reports on the top stories from around the nation and across the globe.",
        "next_title": "Wheel of Fortune"
    },
    "8.1": {
        "network": "FOX",
        "station": "FOX",
        "title": "FOX 8 News at 6:00 PM",
        "start_time": "6:00 PM",
        "end_time": "7:00 PM",
        "synopsis": "Northeast Ohio's news leader featuring live breaking news, investigative reports, and Pinpoint Weather.",
        "next_title": "The Big Bang Theory"
    },
    "19.1": {
        "network": "CBS",
        "station": "WOIO-HD",
        "title": "CBS Evening News with Norah O'Donnell",
        "start_time": "6:30 PM",
        "end_time": "7:00 PM",
        "synopsis": "National and international reporting from the worldwide staff of CBS News correspondents.",
        "next_title": "Jeopardy!"
    },
    "23.1": {
        "network": "ION",
        "station": "ION",
        "title": "Law & Order: Special Victims Unit",
        "start_time": "6:00 PM",
        "end_time": "7:00 PM",
        "synopsis": "Captain Olivia Benson leads an elite squad of NYPD detectives investigating sexually based offenses.",
        "next_title": "Law & Order: SVU"
    },
    "25.1": {
        "network": "PBS",
        "station": "WVIZ-HD",
        "title": "PBS NewsHour",
        "start_time": "6:00 PM",
        "end_time": "7:00 PM",
        "synopsis": "Comprehensive and balanced nightly reporting on the day's major national and international news.",
        "next_title": "BBC News America"
    },
    "43.1": {
        "network": "CW",
        "station": "WUAB",
        "title": "Modern Family",
        "start_time": "6:30 PM",
        "end_time": "7:00 PM",
        "synopsis": "Acclaimed comedy following the Pritchett-Dunphy-Tucker clan through modern family life.",
        "next_title": "The CW Primetime"
    },
    "55.1": {
        "network": "CW",
        "station": "WBNX-HD",
        "title": "The King of Queens",
        "start_time": "6:30 PM",
        "end_time": "7:00 PM",
        "synopsis": "Doug Heffernan, a parcel delivery driver, tries to keep peace between his ambitious wife and eccetric father-in-law.",
        "next_title": "Seinfeld"
    },
    "61.1": {
        "network": "Univision",
        "station": "WQHS-DT",
        "title": "Noticiero Univision",
        "start_time": "6:30 PM",
        "end_time": "7:00 PM",
        "synopsis": "Noticias mundiales y reportajes especiales para la comunidad hispanohablante de Estados Unidos.",
        "next_title": "La Rosa de Guadalupe"
    }
}


def _evening(*blocks):
    return [{"start": start, "end": end, "title": title} for start, end, title in blocks]


for _ch, _blocks in {
    "3.1": _evening(
        ("6:00 PM", "6:30 PM", "WKYC Channel 3 News"),
        ("6:30 PM", "7:00 PM", "NBC Nightly News with Lester Holt"),
        ("7:00 PM", "7:30 PM", "Local News at 7:00 PM"),
        ("7:30 PM", "8:00 PM", "Access Hollywood"),
        ("8:00 PM", "9:00 PM", "The Voice"),
        ("9:00 PM", "10:00 PM", "Dateline NBC"),
        ("10:00 PM", "10:30 PM", "WKYC News at 10"),
        ("10:30 PM", "11:00 PM", "The Tonight Show"),
    ),
    "5.1": _evening(
        ("6:00 PM", "6:30 PM", "News 5 at 6"),
        ("6:30 PM", "7:00 PM", "ABC World News Tonight with David Muir"),
        ("7:00 PM", "7:30 PM", "Wheel of Fortune"),
        ("7:30 PM", "8:00 PM", "Jeopardy!"),
        ("8:00 PM", "9:00 PM", "Celebrity Wheel of Fortune"),
        ("9:00 PM", "10:00 PM", "20/20"),
        ("10:00 PM", "11:00 PM", "News 5 at 10"),
    ),
    "8.1": _evening(
        ("6:00 PM", "7:00 PM", "FOX 8 News at 6:00 PM"),
        ("7:00 PM", "7:30 PM", "The Big Bang Theory"),
        ("7:30 PM", "8:00 PM", "The Big Bang Theory"),
        ("8:00 PM", "9:00 PM", "FOX Primetime"),
        ("9:00 PM", "10:00 PM", "FOX Primetime"),
        ("10:00 PM", "11:00 PM", "FOX 8 News at 10"),
    ),
    "19.1": _evening(
        ("6:00 PM", "6:30 PM", "19 News at 6"),
        ("6:30 PM", "7:00 PM", "CBS Evening News with Norah O'Donnell"),
        ("7:00 PM", "7:30 PM", "Jeopardy!"),
        ("7:30 PM", "8:00 PM", "Wheel of Fortune"),
        ("8:00 PM", "9:00 PM", "CBS Primetime"),
        ("9:00 PM", "10:00 PM", "CBS Primetime"),
        ("10:00 PM", "11:00 PM", "19 News at 10"),
    ),
    "23.1": _evening(
        ("6:00 PM", "7:00 PM", "Law & Order: Special Victims Unit"),
        ("7:00 PM", "8:00 PM", "Law & Order: SVU"),
        ("8:00 PM", "9:00 PM", "Law & Order"),
        ("9:00 PM", "10:00 PM", "Criminal Minds"),
        ("10:00 PM", "11:00 PM", "Law & Order: SVU"),
    ),
    "25.1": _evening(
        ("6:00 PM", "7:00 PM", "PBS NewsHour"),
        ("7:00 PM", "8:00 PM", "BBC News America"),
        ("8:00 PM", "9:00 PM", "Nature"),
        ("9:00 PM", "10:00 PM", "NOVA"),
        ("10:00 PM", "11:00 PM", "Amanpour and Company"),
    ),
    "43.1": _evening(
        ("6:00 PM", "6:30 PM", "Family Feud"),
        ("6:30 PM", "7:00 PM", "Modern Family"),
        ("7:00 PM", "8:00 PM", "The CW Primetime"),
        ("8:00 PM", "9:00 PM", "The CW Primetime"),
        ("9:00 PM", "10:00 PM", "The CW Primetime"),
        ("10:00 PM", "11:00 PM", "Seinfeld"),
    ),
    "55.1": _evening(
        ("6:00 PM", "6:30 PM", "The King of Queens"),
        ("6:30 PM", "7:00 PM", "The King of Queens"),
        ("7:00 PM", "7:30 PM", "Seinfeld"),
        ("7:30 PM", "8:00 PM", "Seinfeld"),
        ("8:00 PM", "9:00 PM", "Friends"),
        ("9:00 PM", "10:00 PM", "Friends"),
        ("10:00 PM", "11:00 PM", "The King of Queens"),
    ),
    "61.1": _evening(
        ("6:00 PM", "6:30 PM", "Noticias"),
        ("6:30 PM", "7:00 PM", "Noticiero Univision"),
        ("7:00 PM", "8:00 PM", "La Rosa de Guadalupe"),
        ("8:00 PM", "9:00 PM", "Novela"),
        ("9:00 PM", "10:00 PM", "Novela"),
        ("10:00 PM", "11:00 PM", "Noticiero Univision: Edición Nocturna"),
    ),
}.items():
    if _ch in BROADCAST_SCHEDULES:
        BROADCAST_SCHEDULES[_ch]["programs"] = _blocks


EVENING_SLOTS = [
    "6:00 PM", "6:30 PM", "7:00 PM", "7:30 PM",
    "8:00 PM", "8:30 PM", "9:00 PM", "9:30 PM",
    "10:00 PM", "10:30 PM",
]


def _ensure_programs(channels: Dict[str, Any]) -> bool:
    changed = False
    for ch_num, info in channels.items():
        if not isinstance(info, dict) or info.get("programs"):
            continue
        template = BROADCAST_SCHEDULES.get(ch_num)
        if template and template.get("programs"):
            info["programs"] = list(template["programs"])
            changed = True
    return changed


def _write_guide(payload: Dict[str, Any], target: str) -> None:
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = f"{target}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, target)


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


def now_and_next(
    programs: Optional[List[Dict[str, Any]]],
    now_minutes: Optional[int] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Program covering now_minutes, then the following block."""
    rows = [p for p in (programs or []) if isinstance(p, dict)]
    if not rows:
        return None, None
    clock = _now_minutes() if now_minutes is None else int(now_minutes)
    covering_idx = None
    for i, prog in enumerate(rows):
        start = parse_minutes(str(prog.get("start") or prog.get("start_time") or ""))
        end = parse_minutes(str(prog.get("end") or prog.get("end_time") or ""))
        if start < 0:
            continue
        when = clock
        if end < 0:
            end = start + 30
        if end <= start:
            end += 24 * 60
            if when < start:
                when += 24 * 60
        if start <= when < end:
            covering_idx = i
            break
    if covering_idx is None:
        return None, None
    nxt = rows[covering_idx + 1] if covering_idx + 1 < len(rows) else None
    return rows[covering_idx], nxt


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
    number = _channel_number(channel)
    template = BROADCAST_SCHEDULES.get(number) or {}
    if prior.get("source") == "psip":
        programs = list(prior.get("programs") or [])
    elif prior.get("programs"):
        programs = list(prior.get("programs"))
    else:
        programs = list(template.get("programs") or [])
    now_prog, next_prog = now_and_next(programs)
    title = (now_prog or {}).get("title") or prior.get("title") or template.get("title") or "Live"
    start = (now_prog or {}).get("start") or prior.get("start_time") or template.get("start_time") or ""
    end = (now_prog or {}).get("end") or prior.get("end_time") or template.get("end_time") or ""
    next_title = (next_prog or {}).get("title") or prior.get("next_title") or template.get("next_title") or ""
    return {
        "network": channel.get("network") or prior.get("network") or template.get("network") or "",
        "station": channel.get("callsign") or prior.get("station") or template.get("station") or "",
        "tune_name": channel.get("tune_name") or channel.get("name") or prior.get("tune_name") or "",
        "callsign": channel.get("callsign") or prior.get("callsign") or "",
        "display_name": channel.get("display_name") or channel.get("name") or prior.get("display_name") or "",
        "programs": list(programs),
        "is_translator": bool(channel.get("is_translator") or prior.get("is_translator")),
        "source": prior.get("source") or ("template" if programs and number in BROADCAST_SCHEDULES else ""),
        "title": title,
        "start_time": start,
        "end_time": end,
        "next_title": next_title,
        "synopsis": prior.get("synopsis") or template.get("synopsis") or "",
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
        if next_prog:
            channels[number]["next_title"] = next_prog.get("title") or ""


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


def refresh_guide(
    channels: Optional[List[Dict[str, Any]]] = None,
    guide_path: Optional[str] = None,
    channels_path: Optional[str] = None,
    grabber: Optional[Callable[[], Dict[str, List[Dict[str, Any]]]]] = None,
    sessions: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """
    Write guide.json from the scanned lineup.
    Optional grabber fills programs; it must not run while a recording holds Tuner 1.
    """
    target = guide_path or GUIDE_JSON_PATH
    lineup = channels
    if lineup is None:
        lineup = _read_channels_file(channels_path or CHANNELS_JSON_PATH)
    existing: Dict[str, Any] = {}
    if os.path.exists(target):
        try:
            with open(target, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict) and isinstance(loaded.get("channels"), dict):
                existing = loaded["channels"]
        except (OSError, json.JSONDecodeError):
            existing = {}
    if lineup:
        merged = merge_lineup(lineup, existing)
    else:
        merged = dict(existing) if existing else dict(BROADCAST_SCHEDULES)
        _ensure_programs(merged)
    skipped = False
    if grabber is not None:
        if epg_tuner_held(sessions):
            skipped = True
        else:
            apply_program_events(merged, grabber() or {})
    payload = {"updated_at": time.time(), "channels": merged, "source": "lineup"}
    _write_guide(payload, target)
    return {"skipped": skipped, "channels": merged}


def sync_guide_from_channels(channels: List[Dict[str, Any]], guide_path: Optional[str] = None) -> Dict[str, Any]:
    return refresh_guide(channels=channels, guide_path=guide_path, grabber=None, sessions=[])


def load_guide(guide_path: Optional[str] = None) -> Dict[str, Any]:
    """Loads EPG data from guide.json. If missing, initializes default broadcast guide."""
    target = guide_path or GUIDE_JSON_PATH
    if os.path.exists(target):
        try:
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                if _ensure_programs(data.get("channels", {})):
                    data["updated_at"] = time.time()
                    _write_guide(data, target)
                return data
        except Exception:
            pass
    return save_default_guide(target)


def save_default_guide(guide_path: Optional[str] = None) -> Dict[str, Any]:
    """Writes default broadcast schedules to guide.json."""
    target = guide_path or GUIDE_JSON_PATH
    payload = {
        "updated_at": time.time(),
        "channels": BROADCAST_SCHEDULES
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
    _ensure_programs(channels_sched)
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

