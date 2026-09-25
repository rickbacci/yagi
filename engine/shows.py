"""One row per show, from the airings the Guide has seen. For deciding what to record."""

import hashlib
import time
from datetime import datetime, timedelta
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Set

from engine.guide import _fold_title, is_filler_title
from engine.psip import EASTERN, format_clock

# A TV night runs 6 AM to 6 AM. A 1 AM airing belongs to the evening before.
NIGHT_START_HOUR = 6
# Three airings this close together on one channel, one night, is a marathon.
MARATHON_RUN = 3
MARATHON_GAP_SEC = 65 * 60
DEFAULT_AIRING_SEC = 30 * 60

BUCKETS = ("prime", "late", "overnight", "day")


def show_id(key: str, channel: str) -> str:
    """One id per show and channel, so every time-of-day row shares one Record all."""
    return hashlib.sha1(f"{key}|{channel}".encode("utf-8")).hexdigest()[:12]


def bucket_for(dt: datetime) -> str:
    """Prime 8-11 PM, Late 11 PM-2 AM, Overnight 2-6 AM, Day the rest."""
    h = dt.hour
    if 20 <= h < 23:
        return "prime"
    if h >= 23 or h < 2:
        return "late"
    if 2 <= h < 6:
        return "overnight"
    return "day"


def night_of(dt: datetime):
    return (dt - timedelta(hours=NIGHT_START_HOUR)).date()


def _short_clock(dt: datetime) -> str:
    """11 PM, 1:30 AM."""
    text = format_clock(dt)
    return text.replace(":00 ", " ")


def _clock_from_minutes(minutes: float) -> datetime:
    base = datetime(2000, 1, 1, tzinfo=EASTERN)
    return base + timedelta(minutes=int(round(minutes)) % (24 * 60))


def _night_minutes(dt: datetime) -> float:
    """Minutes since 6 AM, so 1 AM sorts after 11 PM."""
    return ((dt.hour - NIGHT_START_HOUR) % 24) * 60 + dt.minute


def _weekday_plural(night) -> str:
    return ("Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays")[night.weekday()]


def _pattern(bucket: str, nights: List[Any], longest_run: int, longest_sec: float, observed_weekend: bool) -> str:
    daytime = bucket == "day"
    repeat = ""
    if len(nights) >= 3:
        weekday_only = all(n.weekday() < 5 for n in nights)
        if weekday_only and observed_weekend:
            repeat = "Weekdays" if daytime else "Weeknights"
        else:
            repeat = "Daily" if daytime else "Nightly"
    elif len(nights) == 2:
        a, b = sorted(nights)
        if a.weekday() == b.weekday() and (b - a).days >= 6:
            repeat = _weekday_plural(a)
    marathon = longest_run >= MARATHON_RUN and longest_sec >= 90 * 60
    if marathon:
        return f"{repeat} marathon" if repeat else "Marathon"
    return repeat


def _blocks(starts: List[tuple]) -> List[List[tuple]]:
    """Back-to-back airings on one channel, one night."""
    blocks: List[List[tuple]] = []
    for airing in starts:
        if blocks:
            prev = blocks[-1][-1]
            close = (airing[0] - prev[0]).total_seconds() <= MARATHON_GAP_SEC
            if close and night_of(airing[0]) == night_of(prev[0]):
                blocks[-1].append(airing)
                continue
        blocks.append([airing])
    return blocks


def build_shows(
    airings: Iterable[Dict[str, Any]],
    hidden: Optional[Iterable[str]] = None,
    tune_names: Optional[Dict[str, str]] = None,
    now: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """One row per show, channel, and time of day. Each has a pattern, a time range, and its next airing."""
    stamp = time.time() if now is None else float(now)
    hidden_set = {str(h) for h in (hidden or [])}
    tunes = tune_names or {}

    by_channel: Dict[tuple, List[tuple]] = {}
    titles: Dict[str, str] = {}
    observed_nights: Set[Any] = set()
    seen: Set[tuple] = set()
    for item in airings or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        channel = str(item.get("channel") or "").strip()
        start = int(item.get("start") or 0)
        if not title or not channel or start <= 0:
            continue
        dt = datetime.fromtimestamp(start, EASTERN)
        observed_nights.add(night_of(dt))
        key = _fold_title(title)
        if is_filler_title(title) or channel in hidden_set or (key, channel, start) in seen:
            continue
        seen.add((key, channel, start))
        titles.setdefault(key, title)
        dur = int(item.get("duration_sec") or 0) or DEFAULT_AIRING_SEC
        by_channel.setdefault((key, channel), []).append((dt, dur))

    # An all-day marathon is split at the time-of-day lines, so each pill
    # shows only what airs in its window.
    rows: Dict[tuple, List[List[tuple]]] = {}
    for (key, channel), starts in by_channel.items():
        for block in _blocks(sorted(starts)):
            piece: List[tuple] = []
            for airing in block:
                if piece and bucket_for(airing[0]) != bucket_for(piece[0][0]):
                    rows.setdefault((key, channel, bucket_for(piece[0][0])), []).append(piece)
                    piece = []
                piece.append(airing)
            rows.setdefault((key, channel, bucket_for(piece[0][0])), []).append(piece)

    observed_weekend = any(n.weekday() >= 5 for n in observed_nights)
    shows: List[Dict[str, Any]] = []
    for (key, channel, bucket), blocks in rows.items():
        per_night: Dict[Any, List[datetime]] = {}
        airs: List[tuple] = []
        longest_run = 0
        longest_sec = 0.0
        for block in blocks:
            first, last = block[0], block[-1]
            end = last[0] + timedelta(seconds=last[1])
            span = per_night.setdefault(night_of(first[0]), [first[0], end])
            span[0] = min(span[0], first[0])
            span[1] = max(span[1], end)
            longest_run = max(longest_run, len(block))
            longest_sec = max(longest_sec, (end - first[0]).total_seconds())
            airs.extend(block)
        airs.sort()

        first_min = median(_night_minutes(span[0]) for span in per_night.values())
        last_min = median(_night_minutes(span[1]) for span in per_night.values())
        when = "{}–{}".format(
            _short_clock(_clock_from_minutes(first_min + NIGHT_START_HOUR * 60)),
            _short_clock(_clock_from_minutes(last_min + NIGHT_START_HOUR * 60)),
        )
        pattern = _pattern(bucket, list(per_night), longest_run, longest_sec, observed_weekend)

        nxt = None
        for dt, dur in airs:
            if dt.timestamp() + dur > stamp:
                nxt = {
                    "start_unix": int(dt.timestamp()),
                    "clock": format_clock(dt),
                    "day": dt.strftime("%a"),
                    "duration_sec": dur,
                    "on_now": dt.timestamp() <= stamp,
                }
                break

        shows.append({
            "id": show_id(key, channel),
            "title": titles[key],
            "channel": channel,
            "tune_name": tunes.get(channel, ""),
            "bucket": bucket,
            "buckets": [bucket],
            "pattern": pattern,
            "when": when,
            "label": f"{pattern} {when}" if pattern else when,
            "nights": len(per_night),
            "airings": len(airs),
            "next": nxt,
            "_sort": first_min,
        })

    shows.sort(key=lambda s: (s["_sort"], s["title"].lower()))
    for show in shows:
        del show["_sort"]
    return shows


def load_shows(now: Optional[float] = None) -> List[Dict[str, Any]]:
    """Shows from the saved history, minus hidden stations."""
    from engine.guide import _load_history, _read_channels_file
    from engine.hidden import load_hidden
    from engine.paths import CHANNELS_JSON_PATH, GUIDE_HISTORY_PATH

    history = _load_history(GUIDE_HISTORY_PATH)
    tunes = {
        str(ch.get("channel_number") or ""): str(ch.get("tune_name") or ch.get("name") or "")
        for ch in _read_channels_file(CHANNELS_JSON_PATH)
    }
    return build_shows(history.get("airings") or [], hidden=load_hidden(), tune_names=tunes, now=now)
