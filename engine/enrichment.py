"""
Omarchy TV - Channel Metadata Enrichment & Station Mapping
Maps raw ATSC RF scan entries to user-friendly Major.Minor channel numbers,
network affiliations (NBC, ABC, CBS, FOX, PBS, CW), and human callsigns.
"""

from typing import Dict, Any, List, Optional


# Known Cleveland/Akron/Northeast Ohio market broadcast mappings
# Key: (frequency_hz, service_id) -> metadata
KNOWN_STATION_MAP: Dict[tuple, Dict[str, Any]] = {
    # RF 7 (177.028 MHz) - Daystar / WCDN
    (177028615, 1): {"major": 53, "minor": 1, "network": "Daystar", "callsign": "Daystar", "name": "Daystar TV"},
    (177028615, 2): {"major": 53, "minor": 2, "network": "Daystar", "callsign": "WCDN-2", "name": "Daystar Español"},
    (177028615, 3): {"major": 53, "minor": 3, "network": "Daystar", "callsign": "WCDN-3", "name": "WCDN-LD3"},

    # RF 8 (183.028 MHz) - WJW FOX 8 & WBNX CW 55
    (183028615, 3): {"major": 8, "minor": 1, "network": "FOX", "callsign": "WJW", "name": "FOX 8 (WJW)"},
    (183028615, 4): {"major": 8, "minor": 2, "network": "Antenna TV", "callsign": "WJW-2", "name": "Antenna TV"},
    (183028615, 5): {"major": 8, "minor": 3, "network": "Comet", "callsign": "WJW-3", "name": "Comet TV"},
    (183028615, 6): {"major": 8, "minor": 4, "network": "Charge!", "callsign": "WJW-4", "name": "Charge!"},
    (183028615, 7): {"major": 55, "minor": 1, "network": "CW", "callsign": "WBNX", "name": "CW 55 (WBNX)"},

    # RF 10 (195.028 MHz) - WOIO CBS 19 & WUAB 43
    (195028615, 2): {"major": 19, "minor": 1, "network": "CBS", "callsign": "WOIO", "name": "CBS 19 (WOIO)"},
    (195028615, 3): {"major": 19, "minor": 2, "network": "MeTV", "callsign": "WOIO-2", "name": "MeTV"},
    (195028615, 4): {"major": 43, "minor": 1, "network": "CW", "callsign": "WUAB", "name": "The 43 (WUAB)"},
    (195028615, 5): {"major": 19, "minor": 3, "network": "Outlaw", "callsign": "WOIO-3", "name": "Outlaw"},
    (195028615, 6): {"major": 43, "minor": 2, "network": "Defy", "callsign": "WUAB-2", "name": "Defy"},
    (195028615, 7): {"major": 19, "minor": 4, "network": "Oxygen", "callsign": "WOIO-4", "name": "Oxygen True Crime"},
    (195028615, 8): {"major": 43, "minor": 3, "network": "The 365", "callsign": "WUAB-3", "name": "The 365"},

    # RF 15 (479.028 MHz) - WEWS ABC 5
    (479028615, 3): {"major": 5, "minor": 1, "network": "ABC", "callsign": "WEWS", "name": "ABC News 5 (WEWS)"},
    (479028615, 4): {"major": 5, "minor": 2, "network": "Grit", "callsign": "WEWS-2", "name": "Grit"},
    (479028615, 5): {"major": 5, "minor": 3, "network": "Laff", "callsign": "WEWS-3", "name": "Laff"},
    (479028615, 6): {"major": 5, "minor": 4, "network": "Ion Plus", "callsign": "WEWS-4", "name": "Ion Plus"},
    (479028615, 7): {"major": 5, "minor": 5, "network": "HSN", "callsign": "WEWS-5", "name": "HSN"},
    (479028615, 8): {"major": 5, "minor": 6, "network": "QVC", "callsign": "WEWS-6", "name": "QVC"},
    (479028615, 9): {"major": 5, "minor": 7, "network": "Rewind", "callsign": "WEWS-7", "name": "Rewind TV"},
    (479028615, 10): {"major": 5, "minor": 8, "network": "Heroes", "callsign": "WEWS-8", "name": "Heroes & Icons"},

    # RF 16 (485.028 MHz) - WRAP-LD
    (485028615, 1): {"major": 32, "minor": 1, "network": "WRAP", "callsign": "WRAP", "name": "WRAP D1"},
    (485028615, 2): {"major": 32, "minor": 2, "network": "WRAP", "callsign": "WRAP-2", "name": "WRAP D2"},
    (485028615, 3): {"major": 32, "minor": 3, "network": "WRAP", "callsign": "WRAP-3", "name": "WRAP D3"},
    (485028615, 4): {"major": 32, "minor": 4, "network": "WRAP", "callsign": "WRAP-4", "name": "WRAP D4"},

    # RF 19 (503.028 MHz) - WKYC NBC 3
    (503028615, 1): {"major": 3, "minor": 1, "network": "NBC", "callsign": "WKYC", "name": "NBC 3 (WKYC)"},
    (503028615, 2): {"major": 3, "minor": 2, "network": "Crime", "callsign": "WKYC-2", "name": "True Crime Network"},
    (503028615, 3): {"major": 3, "minor": 3, "network": "Cozi", "callsign": "WKYC-3", "name": "Cozi TV"},
    (503028615, 4): {"major": 3, "minor": 4, "network": "Quest", "callsign": "WKYC-4", "name": "Quest"},
    (503028615, 5): {"major": 3, "minor": 5, "network": "Nest", "callsign": "WKYC-5", "name": "The Nest"},
    (503028615, 6): {"major": 3, "minor": 6, "network": "ShopLC", "callsign": "WKYC-6", "name": "Shop LC"},
    (503028615, 7): {"major": 3, "minor": 7, "network": "QVC2", "callsign": "WKYC-7", "name": "QVC2"},
    (503028615, 8): {"major": 3, "minor": 8, "network": "StartTV", "callsign": "WKYC-8", "name": "Start TV"},

    # RF 20 (509.028 MHz) - WOIO Telemundo & Repeaters
    (509028615, 3): {"major": 19, "minor": 5, "network": "Telemundo", "callsign": "WTCL", "name": "Telemundo 19"},
    (509028615, 4): {"major": 19, "minor": 10, "network": "CBS", "callsign": "WOIO-DRT", "name": "CBS 19 (DRT)"},
    (509028615, 5): {"major": 19, "minor": 6, "network": "Rewind", "callsign": "WOIO-6", "name": "Rewind TV"},

    # RF 21 (515.028 MHz) - WQDI-LD
    (515028615, 1001): {"major": 33, "minor": 1, "network": "WQDI", "callsign": "WQDI", "name": "WQDI-LD 1"},
    (515028615, 1002): {"major": 33, "minor": 2, "network": "WQDI", "callsign": "WQDI-2", "name": "WQDI-LD 2"},
    (515028615, 1003): {"major": 33, "minor": 3, "network": "WQDI", "callsign": "WQDI-3", "name": "WQDI-LD 3"},
    (515028615, 1004): {"major": 33, "minor": 4, "network": "WQDI", "callsign": "WQDI-4", "name": "WQDI-LD 4"},
    (515028615, 1005): {"major": 33, "minor": 5, "network": "WQDI", "callsign": "WQDI-5", "name": "WQDI-LD 5"},
    (515028615, 1006): {"major": 33, "minor": 6, "network": "WQDI", "callsign": "WQDI-6", "name": "WQDI-LD 6"},
    (515028615, 1007): {"major": 33, "minor": 7, "network": "WQDI", "callsign": "WQDI-7", "name": "WQDI-LD 7"},

    # RF 22 (521.028 MHz) - WVPX ION 23
    (521028615, 3): {"major": 23, "minor": 1, "network": "ION", "callsign": "WVPX", "name": "ION (WVPX)"},
    (521028615, 4): {"major": 23, "minor": 2, "network": "Court TV", "callsign": "WVPX-2", "name": "Court TV"},
    (521028615, 5): {"major": 23, "minor": 3, "network": "Busted", "callsign": "WVPX-3", "name": "Busted"},
    (521028615, 6): {"major": 23, "minor": 4, "network": "Mystery", "callsign": "WVPX-4", "name": "Ion Mystery"},
    (521028615, 8): {"major": 23, "minor": 5, "network": "QVC", "callsign": "WVPX-5", "name": "QVC"},
    (521028615, 9): {"major": 23, "minor": 6, "network": "Bounce", "callsign": "WVPX-6", "name": "Bounce TV"},
    (521028615, 10): {"major": 23, "minor": 7, "network": "HSN", "callsign": "WVPX-7", "name": "HSN"},
    (521028615, 11): {"major": 23, "minor": 8, "network": "BUZZR", "callsign": "WVPX-8", "name": "BUZZR"},

    # RF 23 (527.028 MHz) - KONV-LD
    (527028615, 1001): {"major": 28, "minor": 1, "network": "KONV", "callsign": "KONV", "name": "KONV-LD 1"},
    (527028615, 1002): {"major": 28, "minor": 2, "network": "KONV", "callsign": "KONV-2", "name": "KONV-LD 2"},
    (527028615, 1003): {"major": 28, "minor": 3, "network": "KONV", "callsign": "KONV-3", "name": "KONV-LD 3"},
    (527028615, 1004): {"major": 28, "minor": 4, "network": "KONV", "callsign": "KONV-4", "name": "KONV-LD 4"},
    (527028615, 1005): {"major": 28, "minor": 5, "network": "KONV", "callsign": "KONV-5", "name": "KONV-LD 5"},
    (527028615, 1006): {"major": 28, "minor": 6, "network": "KONV", "callsign": "KONV-6", "name": "KONV-LD 6"},
    (527028615, 1007): {"major": 28, "minor": 7, "network": "KONV", "callsign": "KONV-7", "name": "KONV-LD 7"},

    # RF 24 (533.028 MHz) - Western Reserve PBS WEAO & WRLM
    (533028615, 3): {"major": 49, "minor": 1, "network": "PBS", "callsign": "WEAO", "name": "PBS Western Reserve (WEAO)"},
    (533028615, 4): {"major": 49, "minor": 2, "network": "PBS", "callsign": "WEAO-2", "name": "Fusion"},
    (533028615, 5): {"major": 49, "minor": 3, "network": "PBS", "callsign": "WEAO-3", "name": "First Nations Experience"},
    (533028615, 6): {"major": 47, "minor": 1, "network": "TCT", "callsign": "WRLM", "name": "TCT (WRLM)"},

    # RF 25 (539.028 MHz) - WUEK-LD
    (539028615, 1001): {"major": 26, "minor": 1, "network": "WUEK", "callsign": "WUEK", "name": "WUEK-LD 1"},
    (539028615, 1002): {"major": 26, "minor": 2, "network": "WUEK", "callsign": "WUEK-2", "name": "WUEK-LD 2"},
    (539028615, 1003): {"major": 26, "minor": 3, "network": "WUEK", "callsign": "WUEK-3", "name": "WUEK-LD 3"},
    (539028615, 1004): {"major": 26, "minor": 4, "network": "WUEK", "callsign": "WUEK-4", "name": "WUEK-LD 4"},
    (539028615, 1005): {"major": 26, "minor": 5, "network": "WUEK", "callsign": "WUEK-5", "name": "WUEK-LD 5"},
    (539028615, 1006): {"major": 26, "minor": 6, "network": "WUEK", "callsign": "WUEK-6", "name": "WUEK-LD 6"},
    (539028615, 1007): {"major": 26, "minor": 7, "network": "WUEK", "callsign": "WUEK-7", "name": "WUEK-LD 7"},

    # RF 26 (545.028 MHz) - WEKA-LD
    (545028615, 1001): {"major": 41, "minor": 1, "network": "WEKA", "callsign": "WEKA", "name": "WEKA-LD 1"},
    (545028615, 1002): {"major": 41, "minor": 2, "network": "WEKA", "callsign": "WEKA-2", "name": "WEKA-LD 2"},
    (545028615, 1003): {"major": 41, "minor": 3, "network": "WEKA", "callsign": "WEKA-3", "name": "WEKA-LD 3"},
    (545028615, 1004): {"major": 41, "minor": 4, "network": "WEKA", "callsign": "WEKA-4", "name": "WEKA-LD 4"},
    (545028615, 1005): {"major": 41, "minor": 5, "network": "WEKA", "callsign": "WEKA-5", "name": "WEKA-LD 5"},
    (545028615, 1006): {"major": 41, "minor": 6, "network": "WEKA", "callsign": "WEKA-6", "name": "WEKA-LD 6"},
    (545028615, 1007): {"major": 41, "minor": 7, "network": "WEKA", "callsign": "WEKA-7", "name": "WEKA-LD 7"},

    # RF 27 (551.028 MHz) - Catchy / Toons
    (551028615, 3): {"major": 65, "minor": 1, "network": "Catchy", "callsign": "WAXN-1", "name": "Catchy Comedy"},
    (551028615, 4): {"major": 65, "minor": 2, "network": "Story", "callsign": "WAXN-2", "name": "Story Television"},
    (551028615, 5): {"major": 65, "minor": 3, "network": "Toons", "callsign": "WAXN-3", "name": "MeTV Toons"},
    (551028615, 6): {"major": 65, "minor": 4, "network": "Movies!", "callsign": "WAXN-4", "name": "Movies!"},
    (551028615, 7): {"major": 65, "minor": 5, "network": "Dabl", "callsign": "WAXN-5", "name": "Dabl"},
    (551028615, 8): {"major": 65, "minor": 6, "network": "West", "callsign": "WAXN-6", "name": "Catchy Westerns"},
    (551028615, 14): {"major": 65, "minor": 7, "network": "EMLW", "callsign": "WAXN-7", "name": "EMLW"},

    # RF 35 (599.028 MHz) - WVIZ PBS Ideastream
    (599028615, 3): {"major": 25, "minor": 1, "network": "PBS", "callsign": "WVIZ", "name": "PBS Ideastream (WVIZ)"},
    (599028615, 4): {"major": 25, "minor": 2, "network": "Ohio Ch", "callsign": "WVIZ-2", "name": "The Ohio Channel"},
    (599028615, 6): {"major": 25, "minor": 3, "network": "Create", "callsign": "WVIZ-3", "name": "Create TV"},
    (599028615, 7): {"major": 25, "minor": 4, "network": "PBS Kids", "callsign": "WVIZ-4", "name": "PBS KIDS"},
    (599028615, 9): {"major": 25, "minor": 5, "network": "NPR", "callsign": "WKSU", "name": "WKSU 89.7 FM"},
    (599028615, 10): {"major": 25, "minor": 6, "network": "Classical", "callsign": "WCLV", "name": "WCLV 90.3 Classical"},
    (599028615, 11): {"major": 25, "minor": 7, "network": "CSCN", "callsign": "CSCN", "name": "Cleveland Sight Center"},

    # RF 36 (605.028 MHz) - WQHS Univision 61
    (605028615, 1): {"major": 61, "minor": 1, "network": "Univision", "callsign": "WQHS", "name": "Univision 61 (WQHS)"},
    (605028615, 2): {"major": 61, "minor": 2, "network": "UniMás", "callsign": "WQHS-2", "name": "UniMás"},
    (605028615, 3): {"major": 61, "minor": 3, "network": "GAC", "callsign": "WQHS-3", "name": "Great American Family"},
    (605028615, 4): {"major": 61, "minor": 4, "network": "Nosey", "callsign": "WQHS-4", "name": "Nosey"},
    (605028615, 5): {"major": 61, "minor": 5, "network": "HSN2", "callsign": "WQHS-5", "name": "HSN2"},
    (605028615, 6): {"major": 61, "minor": 6, "network": "ShopLC", "callsign": "WQHS-6", "name": "Shop LC"},
    (605028615, 7): {"major": 61, "minor": 7, "network": "BT2", "callsign": "WQHS-7", "name": "BT2"},
    (605028615, 8): {"major": 61, "minor": 8, "network": "Movies Gold", "callsign": "WQHS-8", "name": "Movies Gold"},
}


def enrich_channel(channel: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enriches a single raw channel record with virtual channel number,
    network affiliation, callsign, and formatted display name.
    """
    res = dict(channel)
    freq = res.get("frequency", 0)
    sid = res.get("service_id", 0)
    raw_name = res.get("raw_name") or res.get("name") or "Unknown"

    lookup = KNOWN_STATION_MAP.get((freq, sid))
    if lookup:
        res["major"] = lookup["major"]
        res["minor"] = lookup["minor"]
        res["channel_number"] = f"{lookup['major']}.{lookup['minor']}"
        res["network"] = lookup["network"]
        res["callsign"] = lookup["callsign"]
        res["display_name"] = lookup["name"]
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

    # Retain the exact hardware tuning name (MPV channels.conf identifier)
    res["tune_name"] = res.get("raw_name") or res.get("name")
    return res


def enrich_and_sort_channels(channels: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Enriches channel list and sorts by (major, minor) so stations appear in
    the traditional logical order: 3.1 NBC, 5.1 ABC, 8.1 FOX, 19.1 CBS, etc.
    """
    enriched = [enrich_channel(c) for c in channels]

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
