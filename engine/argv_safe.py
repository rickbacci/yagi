"""Keep library paths out of child argv.

Every recording file handed to another process is a neutral hard link
(.yagi-<hex>.ext) on the same inode. There is no check of the title, its
length, or whether the name looks generic. If the link cannot be created,
the child gets an inherited /dev/fd/N instead. The titled path is never
the fallback.
"""

from __future__ import annotations

import os
import uuid
from typing import Iterable, List, Optional, Tuple

_OPEN: dict = {}


def _neutral(path: str) -> bool:
    return os.path.basename(path).startswith(".yagi-")


def _shield_file(path: str) -> bool:
    """A real library file. URLs, sockets, and links we already made are not."""
    if not path or not isinstance(path, str):
        return False
    if path.startswith(("dvb://", "fd://", "/dev/fd/", "/proc/self/fd/")):
        return False
    if _neutral(path):
        return False
    try:
        return os.path.isfile(path)
    except OSError:
        return False


class HeldLinks:
    """Neutral names and inherited fds kept until the child is finished."""

    def __init__(self) -> None:
        self.links: List[str] = []
        self.fds: List[int] = []

    def hide(self, path: str, titles: Iterable[object] = ()) -> str:
        del titles
        if not _shield_file(path):
            return path
        try:
            return self._hardlink(path)
        except OSError:
            return self._fd(path)

    def _hardlink(self, path: str) -> str:
        ext = os.path.splitext(path)[1] or ".ts"
        folder = os.path.dirname(os.path.abspath(path)) or "."
        link = os.path.join(folder, f".yagi-{uuid.uuid4().hex}{ext}")
        os.link(path, link)
        self.links.append(link)
        return link

    def _fd(self, path: str) -> str:
        try:
            fd = os.open(path, os.O_RDWR)
        except OSError as exc:
            raise RuntimeError("refusing to pass a library path on a child command line") from exc
        self.fds.append(fd)
        return f"/dev/fd/{fd}"

    def rewrite(self, cmd: List[str], titles: Iterable[object] = ()) -> List[str]:
        del titles
        out = []
        for arg in cmd:
            prefix, path = _split_opt(arg)
            if path is None:
                out.append(arg)
                continue
            out.append(prefix + self.hide(path) if prefix else self.hide(path))
        return out

    def release(self) -> None:
        for link in self.links:
            try:
                os.unlink(link)
            except OSError:
                pass
        self.links.clear()
        for fd in self.fds:
            try:
                os.close(fd)
            except OSError:
                pass
        self.fds.clear()


def _split_opt(arg: str) -> Tuple[str, Optional[str]]:
    if not isinstance(arg, str) or (arg.startswith("-") and "=" not in arg):
        return "", arg if isinstance(arg, str) and _looks_like_path(arg) else None
    if arg.startswith("--") and "=" in arg:
        prefix, value = arg.split("=", 1)
        if _looks_like_path(value):
            return prefix + "=", value
        return "", None
    if _looks_like_path(arg):
        return "", arg
    return "", None


def _looks_like_path(value: str) -> bool:
    """A library media file. Binaries, sockets, and configs are not titles."""
    if not value or value.startswith(("dvb://", "fd://", "/dev/fd/", "/proc/self/fd/")):
        return False
    return value.lower().endswith((".ts", ".mkv", ".mp4"))


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
