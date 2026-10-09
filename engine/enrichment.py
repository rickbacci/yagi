"""
Yagi - Channel Metadata Enrichment & Station Mapping
Maps raw ATSC RF scan entries to user-friendly Major.Minor channel numbers,
network affiliations (NBC, ABC, CBS, FOX, PBS, CW), and human callsigns.

A local `station_map.json` is optional. Without it, names come from PSIP
and a small network heuristic. Network names are not in the broadcast.
markets/cleveland.json is an example map; copy one into the config dir.
"""

import json
import os
from typing import Dict, Any, List, Optional, Tuple

from engine.paths import STATION_MAP_PATH


# What a station usually shows. Matched from the name it already sends.
_KIND_RULES = (
    ("kids", ("pbs kids", "metv toons", "toons")),
    ("religious", ("daystar", "tbn", "tct", "insp")),
    ("shop", ("shop lc", "shoplc", "hsn", "qvc", "jtv")),
    ("movies", ("movies gold", "movies", "grit", "comet", "charge", "outlaw", "western")),
    ("classic", ("antenna", "heroes", "rewind", "metv", "cozi", "laff", "buzzr", "catchy", "start tv", "ion plus", "bounce")),
    ("network", ("univision", "unimas", "telemundo", "nbc", "abc", "cbs", "fox", "pbs", "ion", "cw")),
)


def channel_kind(*parts: str) -> str:
    """network, movies, classic, shop, religious, kids — or empty when we don't know."""
    blob = " ".join(str(part or "") for part in parts).lower().replace("!", " ").replace("-", " ").replace("&", " ")
    blob = " ".join(blob.split())
    padded = f" {blob} "
    for kind, phrases in _KIND_RULES:
        for phrase in phrases:
            if " " in phrase:
                if phrase in blob:
                    return kind
            elif f" {phrase} " in padded:
                return kind
    return ""


StationKey = Tuple[int, int]
StationMeta = Dict[str, Any]


def load_station_map(path: str) -> Dict[StationKey, StationMeta]:
    """Parse a market file. Missing or bad JSON is an empty map."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    rows = data.get("stations") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return {}
    out: Dict[StationKey, StationMeta] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            freq = int(row["frequency"])
            sid = int(row["service_id"])
        except (KeyError, TypeError, ValueError):
            continue
        meta = {k: v for k, v in row.items() if k not in ("frequency", "service_id")}
        if "major" not in meta or "minor" not in meta:
            continue
        out[(freq, sid)] = meta
    return out


_station_map_cache: Optional[Tuple[str, float, Dict[StationKey, StationMeta]]] = None


def station_map(path: Optional[str] = None) -> Dict[StationKey, StationMeta]:
    """Config-dir map, or empty. Not the repo Cleveland file."""
    global _station_map_cache
    target = path or STATION_MAP_PATH
    try:
        mtime = os.path.getmtime(target)
    except OSError:
        _station_map_cache = (target, -1.0, {})
        return {}
    if _station_map_cache and _station_map_cache[0] == target and _station_map_cache[1] == mtime:
        return _station_map_cache[2]
    loaded = load_station_map(target)
    _station_map_cache = (target, mtime, loaded)
    return loaded


def enrich_channel(
    channel: Dict[str, Any],
    known: Optional[Dict[StationKey, StationMeta]] = None,
) -> Dict[str, Any]:
    """
    Enriches a single raw channel record with virtual channel number,
    network affiliation, callsign, and formatted display name.
    """
    res = dict(channel)
    freq = res.get("frequency", 0)
    sid = res.get("service_id", 0)
    raw_name = res.get("raw_name") or res.get("name") or "Unknown"

    lookup = (known if known is not None else station_map()).get((freq, sid))
    if lookup:
        res["major"] = lookup["major"]
        res["minor"] = lookup["minor"]
        res["channel_number"] = f"{lookup['major']}.{lookup['minor']}"
        res["network"] = lookup["network"]
        res["callsign"] = lookup["callsign"]
        res["display_name"] = lookup["name"]
        res["is_translator"] = bool(lookup.get("translator"))
    else:
        # Fallback heuristic: check if raw_name contains a callsign or network
        res["callsign"] = raw_name.split()[0].replace("-HD", "").replace("-DT", "")
        # Major networks heuristic
        upper_name = raw_name.upper()
        if "FOX" in upper_name:
            res["network"] = "FOX"
        elif "NBC" in upper_name:
            res["network"] = "NBC"
        elif "ABC" in upper_name:
            res["network"] = "ABC"
        elif "CBS" in upper_name:
            res["network"] = "CBS"
        elif "PBS" in upper_name:
            res["network"] = "PBS"
        elif "CW" in upper_name:
            res["network"] = "CW"
        elif "ION" in upper_name:
            res["network"] = "ION"
        else:
            res["network"] = "OTA"

        # Generate a fallback channel number if not available
        res["major"] = res.get("major") or (res.get("physical_channel") or (freq // 10000000))
        res["minor"] = res.get("minor") or (sid if isinstance(sid, int) else 1)
        res["channel_number"] = f"{res['major']}.{res['minor']}"
        res["display_name"] = f"{res['channel_number']} {raw_name}"
        res["is_translator"] = False

    blob = f"{res.get('callsign', '')} {res.get('display_name', '')} {raw_name}".upper()
    if "DRT" in blob or "TRANSLATOR" in blob:
        res["is_translator"] = True

    # Retain the exact hardware tuning name (MPV channels.conf identifier)
    res["tune_name"] = res.get("raw_name") or res.get("name")
    res["kind"] = channel_kind(
        res.get("network"),
        res.get("display_name"),
        res.get("callsign"),
        res.get("name"),
    )
    return res


def enrich_and_sort_channels(
    channels: List[Dict[str, Any]],
    known: Optional[Dict[StationKey, StationMeta]] = None,
) -> List[Dict[str, Any]]:
    """
    Enriches channel list and sorts by (major, minor) so stations appear in
    the traditional logical order: 3.1 NBC, 5.1 ABC, 8.1 FOX, 19.1 CBS, etc.
    """
    table = known if known is not None else station_map()
    enriched = [enrich_channel(c, known=table) for c in channels]

    def sort_key(ch):
        major = ch.get("major", 999)
        minor = ch.get("minor", 999)
        return (major if isinstance(major, int) else 999, minor if isinstance(minor, int) else 999)

    enriched.sort(key=sort_key)
    return enriched


def match_channel(query: str, channels: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    Resolves user tuning queries such as:
      - Channel number: "3", "3.1", "5.1", "8", "43", "55"
      - Network: "NBC", "ABC", "FOX", "CBS", "CW", "PBS"
      - Callsign: "WKYC", "WEWS", "WJW", "WOIO", "WUAB", "WBNX", "WVIZ"
      - Name / tune_name: "WKYC-HD", "FOX", "WEWSHD"
    """
    q = str(query).strip()
    if not q:
        return None

    q_lower = q.lower()

    # 1. Exact match by channel_number (e.g. "3.1", "5.1", "8.1", "43.1")
    for ch in channels:
        if ch.get("channel_number") == q:
            return ch

    # 2. Integer major channel match (e.g. "3" -> 3.1, "5" -> 5.1, "8" -> 8.1, "43" -> 43.1, "55" -> 55.1)
    if q.isdigit():
        major_num = int(q)
        # Prioritize .1 subchannel for the major channel
        for ch in channels:
            if ch.get("major") == major_num and ch.get("minor") == 1:
                return ch
        # Fallback to any channel with this major number
        for ch in channels:
            if ch.get("major") == major_num:
                return ch

    # 3. Exact match by network (e.g. "NBC", "ABC", "FOX", "CBS", "PBS", "CW")
    for ch in channels:
        if (ch.get("network") or "").lower() == q_lower and ch.get("minor") == 1:
            return ch
    for ch in channels:
        if (ch.get("network") or "").lower() == q_lower:
            return ch

    # 4. Exact match by callsign or tune_name
    for ch in channels:
        if (ch.get("callsign") or "").lower() == q_lower:
            return ch
        if (ch.get("tune_name") or ch.get("name") or "").lower() == q_lower:
            return ch

    # 5. Case-insensitive substring match
    for ch in channels:
        display = (ch.get("display_name") or "").lower()
        name = (ch.get("name") or "").lower()
        if q_lower in display or q_lower in name:
            return ch

    return None
