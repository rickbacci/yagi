"""
Omarchy TV - Electronic Program Guide (EPG) Engine
Manages schedule data, program synopses, and airings in guide.json.
Provides current and upcoming show information for major broadcast stations.
"""

import os
import json
import time
from typing import Dict, Any, Optional, List
from engine.paths import GUIDE_JSON_PATH


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


def load_guide(guide_path: Optional[str] = None) -> Dict[str, Any]:
    """Loads EPG data from guide.json. If missing, initializes default broadcast guide."""
    target = guide_path or GUIDE_JSON_PATH
    if os.path.exists(target):
        try:
            with open(target, "r", encoding="utf-8") as f:
                return json.load(f)
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
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
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
