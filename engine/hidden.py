"""Stations set aside from Watchable and Favorites. Keyed by channel number."""

import json
import os
from typing import Any, Dict, List, Optional

from engine.paths import HIDDEN_JSON_PATH

# First-run pile. 19.10 stays; it carries the longer CBS 19 guide.
SEED_HIDDEN = [
    "19.1",
    "23.5",
    "23.7",
    "26.1",
    "26.4",
    "25.5",
    "25.6",
    "25.7",
    "28.1",
    "28.3",
    "28.4",
    "32.1",
    "32.2",
    "32.3",
    "32.4",
    "33.1",
    "33.2",
    "33.3",
    "33.4",
    "33.5",
    "33.6",
    "33.7",
    "41.1",
    "41.2",
    "65.7",
]


def channel_number(ch: Optional[Dict[str, Any]]) -> str:
    if not ch:
        return ""
    return str(ch.get("channel_number") or "").strip()


def load_hidden(path: Optional[str] = None, seed: bool = True) -> List[str]:
    target = path or HIDDEN_JSON_PATH
    if not os.path.exists(target):
        if seed:
            save_hidden(list(SEED_HIDDEN), target)
            return list(SEED_HIDDEN)
        return []
    try:
        with open(target, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    items = data.get("channels") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    out = []
    for item in items:
        num = str(item or "").strip()
        if num and num not in out:
            out.append(num)
    return out


def save_hidden(numbers: List[str], path: Optional[str] = None) -> None:
    target = path or HIDDEN_JSON_PATH
    os.makedirs(os.path.dirname(target), exist_ok=True)
    cleaned = []
    for item in numbers:
        num = str(item or "").strip()
        if num and num not in cleaned:
            cleaned.append(num)
    tmp = f"{target}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cleaned, f, indent=2)
    os.replace(tmp, target)


def hide_channel(number: str, path: Optional[str] = None) -> List[str]:
    num = str(number or "").strip()
    items = load_hidden(path)
    if num and num not in items:
        items.append(num)
        save_hidden(items, path)
    return items


def show_channel(number: str, path: Optional[str] = None) -> List[str]:
    num = str(number or "").strip()
    items = [row for row in load_hidden(path) if row != num]
    save_hidden(items, path)
    return items


def is_hidden_channel(ch: Optional[Dict[str, Any]], hidden: Optional[List[Any]]) -> bool:
    num = channel_number(ch)
    if not num:
        return False
    return num in {str(item or "").strip() for item in (hidden or [])}
