"""Keep programme titles out of child argv.

A recording's filename carries the show. Other users can read
/proc/PID/cmdline, so a child is handed a hard link whose name does not.
The titled name stays on disk for the library. The link is the same inode,
so growth, fuser, and playback still see the file.
"""

from __future__ import annotations

import os
import uuid
from typing import Iterable, List, Optional

_OPEN: dict = {}


def _tokens(titles: Iterable[object], path: str = "") -> List[str]:
    from engine.dvr import read_sidecar, sanitize_filename

    raw = [str(item or "").strip() for item in titles]
    if path:
        side = read_sidecar(path)
        raw.append(str(side.get("title") or ""))
        for ep in side.get("episodes") or []:
            if isinstance(ep, dict):
                raw.append(str(ep.get("title") or ""))
    out = []
    for item in raw:
        if len(item) >= 3 and item not in out:
            out.append(item)
        safe = sanitize_filename(item)
        if len(safe) >= 3 and safe not in out and safe != "recording":
            out.append(safe)
    return out


def _leaks(path: str, titles: Iterable[object]) -> bool:
    if not path or path.startswith(("dvb://", "fd://", "/dev/fd/")):
        return False
    try:
        if not os.path.isfile(path):
            return False
    except OSError:
        return False
    base = os.path.basename(path)
    if base.startswith(".yagi-"):
        return False
    return any(token in base for token in _tokens(titles, path))


class HeldLinks:
    """Neutral hard links that stay until the child is done with the path."""

    def __init__(self) -> None:
        self.links: List[str] = []

    def hide(self, path: str, titles: Iterable[object] = ()) -> str:
        if not _leaks(path, titles):
            return path
        ext = os.path.splitext(path)[1] or ".ts"
        folder = os.path.dirname(os.path.abspath(path)) or "."
        link = os.path.join(folder, f".yagi-{uuid.uuid4().hex}{ext}")
        os.link(path, link)
        self.links.append(link)
        return link

    def rewrite(self, cmd: List[str], titles: Iterable[object] = ()) -> List[str]:
        out = []
        for arg in cmd:
            prefix, path = _split_opt(arg)
            if path is None:
                out.append(arg)
                continue
            hidden = self.hide(path, titles)
            out.append(prefix + hidden if prefix else hidden)
        return out

    def release(self) -> None:
        for link in self.links:
            try:
                os.unlink(link)
            except OSError:
                pass
        self.links.clear()


def _split_opt(arg: str):
    if not isinstance(arg, str) or arg.startswith("-") and "=" not in arg:
        return "", arg if _looks_like_path(arg) else None
    if "=" in arg and arg.startswith("--"):
        prefix, value = arg.split("=", 1)
        if _looks_like_path(value):
            return prefix + "=", value
        return "", None
    if _looks_like_path(arg):
        return "", arg
    return "", None


def _looks_like_path(value: str) -> bool:
    if not value or value.startswith(("dvb://", "fd://")):
        return False
    if value.startswith("/") or value.startswith("./") or value.startswith("../"):
        return True
    return os.path.sep in value or value.lower().endswith((".ts", ".mkv", ".mp4", ".json"))


def remember(pid: int, held: HeldLinks) -> None:
    try:
        key = int(pid)
    except (TypeError, ValueError):
        held.release()
        return
    old = _OPEN.pop(key, None)
    if old is not None and old is not held:
        old.release()
    _OPEN[key] = held


def release_pid(pid: Optional[int]) -> None:
    try:
        key = int(pid or 0)
    except (TypeError, ValueError):
        return
    held = _OPEN.pop(key, None)
    if held is not None:
        held.release()
