"""Record all: a show on one channel, any time of day. Each minute its listings join the queue."""

import json
import os
import time
from typing import Any, Dict, List, Optional

from engine.guide import _fold_title, is_filler_title
from engine.paths import CONFIG_DIR, chmod_private_file, ensure_private_dir, state_lock
from engine.psip import GPS_LEAP_SECONDS, GPS_UNIX_OFFSET
from engine.shows import show_id

RULES_PATH = os.path.join(CONFIG_DIR, "record_rules.json")
# Listings reach about five hours ahead. Anything they show inside this is queued.
ARM_HORIZON_SEC = 12 * 3600
# A description this short says nothing about the episode.
MIN_EPISODE_TEXT = 20


def load_rules(path: Optional[str] = None) -> List[Dict[str, Any]]:
    try:
        with open(path or RULES_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    rules = data.get("rules") if isinstance(data, dict) else data
    return _current([r for r in (rules or []) if isinstance(r, dict) and r.get("id")])


def _current(rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Older rules held one time of day and an id per time. One show and channel is one rule."""
    out: List[Dict[str, Any]] = []
    by_id: Dict[str, Dict[str, Any]] = {}
    for rule in rules:
        rule = dict(rule)
        rule.pop("buckets", None)
        if rule.get("key"):
            rule["id"] = show_id(str(rule["key"]), str(rule.get("channel") or ""))
        old = by_id.get(rule["id"])
        if old is None:
            by_id[rule["id"]] = rule
            out.append(rule)
            continue
        for field in ("handled", "seen"):
            old[field] = list(dict.fromkeys(list(old.get(field) or []) + list(rule.get(field) or [])))
    return out


def _stale(path: str) -> bool:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return False
    raw = data.get("rules") if isinstance(data, dict) else data
    raw = [r for r in (raw or []) if isinstance(r, dict) and r.get("id")]
    return raw != load_rules(path)


def save_rules(rules: List[Dict[str, Any]], path: Optional[str] = None) -> None:
    target = path or RULES_PATH
    ensure_private_dir(os.path.dirname(target))
    tmp = f"{target}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"rules": rules}, f, indent=2)
    chmod_private_file(tmp)
    os.replace(tmp, target)


def add_rule(
    title: str,
    channel: str,
    tune_name: str,
    path: Optional[str] = None,
) -> Dict[str, Any]:
    name = (title or "").strip()
    if not name or not (tune_name or "").strip():
        raise ValueError("A show and a station are required.")
    key = _fold_title(name)
    ident = show_id(key, str(channel or ""))
    rule = {
        "id": ident,
        "title": name,
        "key": key,
        "channel": str(channel or ""),
        "tune_name": tune_name.strip(),
        "handled": [],
        "seen": [],
        "created": int(time.time()),
    }
    target = path or RULES_PATH
    with state_lock(target):
        rules = load_rules(target)
        for old in rules:
            if old.get("id") == ident:
                rule["handled"] = list(old.get("handled") or [])
                rule["seen"] = list(old.get("seen") or [])
                rule["created"] = old.get("created") or rule["created"]
        rules = [r for r in rules if r.get("id") != ident]
        rules.append(rule)
        save_rules(rules, target)
    return rule


def remove_rule(rule_id: str, path: Optional[str] = None) -> bool:
    target = path or RULES_PATH
    with state_lock(target):
        rules = load_rules(target)
        kept = [r for r in rules if r.get("id") != rule_id]
        if len(kept) == len(rules):
            return False
        save_rules(kept, target)
    return True


def episode_text(synopsis: Any) -> str:
    text = " ".join(str(synopsis or "").lower().split())
    return text if len(text) >= MIN_EPISODE_TEXT else ""


def note_recorded(rule_id: str, synopsis: Any, path: Optional[str] = None) -> None:
    """An episode this rule recorded. A later airing with the same text is a rerun."""
    text = episode_text(synopsis)
    if not rule_id or not text:
        return
    target = path or RULES_PATH
    with state_lock(target):
        rules = load_rules(target)
        for rule in rules:
            if rule.get("id") == rule_id and text not in rule.setdefault("seen", []):
                rule["seen"].append(text)
                rule["seen"] = rule["seen"][-500:]
        save_rules(rules, target)


def _unix(prog: Dict[str, Any]) -> int:
    try:
        gps = int(prog.get("gps_start") or 0)
    except (TypeError, ValueError):
        return 0
    return gps + GPS_UNIX_OFFSET - GPS_LEAP_SECONDS if gps > 0 else 0


def arm_rules(
    guide_channels: Optional[Dict[str, Any]],
    now: Optional[float] = None,
    rules_path: Optional[str] = None,
    schedule_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Queue each listed airing a rule wants. An airing is queued once, even if you remove it."""
    from engine.schedule import add_later

    stamp = time.time() if now is None else float(now)
    target = rules_path or RULES_PATH
    added: List[Dict[str, Any]] = []
    with state_lock(target):
        rules = load_rules(target)
        changed = _stale(target)
        for rule in rules:
            row = (guide_channels or {}).get(str(rule.get("channel") or ""))
            if not isinstance(row, dict):
                continue
            programs = sorted(
                [p for p in (row.get("programs") or []) if isinstance(p, dict) and _unix(p) > 0],
                key=_unix,
            )
            key = str(rule.get("key") or "")
            mine = [p for p in programs if _fold_title(str(p.get("title") or "")) == key]
            # A blurb every episode shares is the series, not the episode.
            texts = [episode_text(p.get("synopsis")) for p in mine]
            shared = {t for t in texts if t and texts.count(t) > 1}
            handled = rule.setdefault("handled", [])
            seen = set(rule.get("seen") or [])
            for index, prog in enumerate(programs):
                title = str(prog.get("title") or "")
                if _fold_title(title) != key or is_filler_title(title):
                    continue
                start = _unix(prog)
                dur = max(60, int(prog.get("duration_sec") or 0) or 1800)
                if start + dur <= stamp or start > stamp + ARM_HORIZON_SEC:
                    continue
                ident = f"{rule['tune_name']}-{int(prog['gps_start'])}"
                if ident in handled:
                    continue
                handled.append(ident)
                changed = True
                text = episode_text(prog.get("synopsis"))
                if text and text not in shared and text in seen:
                    continue
                extra: Dict[str, Any] = {"rule_id": rule["id"], "synopsis": str(prog.get("synopsis") or "")}
                before = programs[index - 1] if index else None
                after = programs[index + 1] if index + 1 < len(programs) else None
                # Back to back on this channel: no pad, so one episode does not eat the next.
                if before and _fold_title(str(before.get("title") or "")) == key:
                    extra["pad_early_sec"] = 0
                if after and _fold_title(str(after.get("title") or "")) == key:
                    extra["pad_late_sec"] = 0
                added.append(add_later(
                    rule["tune_name"],
                    title,
                    prog["gps_start"],
                    dur,
                    clock=str(prog.get("start") or ""),
                    end_clock=str(prog.get("end") or ""),
                    display_name=str(row.get("display_name") or rule["tune_name"]),
                    extra=extra,
                    path=schedule_path,
                ))
            rule["handled"] = handled[-1000:]
        if changed:
            save_rules(rules, target)
    return added
