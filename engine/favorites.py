"""Favorites are channel numbers. Two channels can share a station name (a
main transmitter and its DRT), so a name would star both."""

import json
import os
import re
from typing import Any, Dict, List, Optional

from engine.paths import CHANNELS_JSON_PATH, FAVORITES_JSON_PATH

_NUMBER = re.compile(r"^\d+(\.\d+)?$")


def _read_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _channels(path: str) -> List[Dict[str, Any]]:
    raw = _read_json(path, [])
    if isinstance(raw, dict):
        raw = raw.get("channels", [])
    return [ch for ch in raw if isinstance(ch, dict)] if isinstance(raw, list) else []


def is_number(entry: Any) -> bool:
    return bool(_NUMBER.match(str(entry or "").strip()))


def _named(entry: str, channels: List[Dict[str, Any]]) -> List[str]:
    want = entry.strip().lower()
    return [str(ch.get("channel_number")) for ch in channels
            if ch.get("channel_number") and want in (str(ch.get("name") or "").lower(), str(ch.get("tune_name") or "").lower())]


def save_favorites(favorites: List[str], path: str = FAVORITES_JSON_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(favorites, f, indent=2)
    os.replace(tmp, path)


def load_favorites(path: str = FAVORITES_JSON_PATH, channels_path: str = CHANNELS_JSON_PATH) -> List[str]:
    """Channel numbers. Names from before are turned into every number they matched, once."""
    raw = _read_json(path, [])
    if not isinstance(raw, list):
        return []
    favs = [str(x).strip() for x in raw if str(x or "").strip()]
    if all(is_number(x) for x in favs):
        return favs
    channels = _channels(channels_path)
    if not channels:
        return favs
    out: List[str] = []
    for entry in favs:
        for num in ([entry] if is_number(entry) else _named(entry, channels) or [entry]):
            if num not in out:
                out.append(num)
    if out != favs:
        save_favorites(out, path)
    return out


def favorite_key(target: str, channels_path: str = CHANNELS_JSON_PATH) -> str:
    """The channel number for what was typed: "8.1", "FOX", "WKYC-HD"."""
    text = str(target or "").strip()
    if is_number(text):
        return text
    from engine.enrichment import match_channel
    matched = match_channel(text, _channels(channels_path))
    return str(matched.get("channel_number")) if matched and matched.get("channel_number") else text


def favorite_label(entry: str, channels_path: str = CHANNELS_JSON_PATH) -> str:
    """"19.10 CBS 19 (DRT)" when the channel is known, else the entry in quotes."""
    text = str(entry or "").strip()
    for ch in _channels(channels_path):
        if str(ch.get("channel_number") or "") == text:
            name = ch.get("display_name") or ch.get("name") or ch.get("tune_name") or ""
            return f"{text} {name}".strip()
    return f"'{text}'"


def is_favorite(ch: Optional[Dict[str, Any]], favorites: Optional[List[Any]]) -> bool:
    if not ch:
        return False
    num = str(ch.get("channel_number") or "").strip()
    for entry in favorites or []:
        text = str(entry or "").strip()
        if is_number(text):
            if text == num:
                return True
        elif text and text.lower() in (str(ch.get("name") or "").lower(), str(ch.get("tune_name") or "").lower()):
            return True
    return False
