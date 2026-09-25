"""
Omarchy TV - Shared Paths & Runtime Security
Centralizes configuration, socket locations, and directories with secure permissions.
"""

import contextlib
import fcntl
import hashlib
import os
import shutil
import threading
import time
from typing import Iterator, List, Optional

DIR_PRIVATE = 0o700
FILE_PRIVATE = 0o600

_XDG_CONFIG = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
CONFIG_DIR = os.path.join(_XDG_CONFIG, "omarchy", "tv")
CHANNELS_JSON_PATH = os.path.join(CONFIG_DIR, "channels.json")
FAVORITES_JSON_PATH = os.path.join(CONFIG_DIR, "favorites.json")
HIDDEN_JSON_PATH = os.path.join(CONFIG_DIR, "hidden.json")
GUIDE_JSON_PATH = os.path.join(CONFIG_DIR, "guide.json")
GUIDE_HISTORY_PATH = os.path.join(CONFIG_DIR, "guide_history.json")
SCAN_STATUS_PATH = os.path.join(CONFIG_DIR, "scan_status.json")
GUIDE_STATUS_PATH = os.path.join(CONFIG_DIR, "guide_status.json")
MPV_CHANNELS_CONF = os.path.join(_XDG_CONFIG, "mpv", "channels.conf")
_XDG_VIDEOS = os.environ.get("XDG_VIDEOS_DIR") or os.path.expanduser("~/Videos")
RECORDINGS_DIR = os.path.join(_XDG_VIDEOS, "TV")
RECORDINGS_ACTIVE_PATH = os.path.join(CONFIG_DIR, "recordings_active.json")
RECORDINGS_INDEX_PATH = os.path.join(CONFIG_DIR, "recordings.json")
SCHEDULE_PATH = os.path.join(CONFIG_DIR, "schedule.json")
PLAYER_STATE_PATH = os.path.join(CONFIG_DIR, "player_state.json")
UI_PREFS_PATH = os.path.join(CONFIG_DIR, "ui_prefs.json")
STATION_MAP_PATH = os.path.join(CONFIG_DIR, "station_map.json")
_XDG_CACHE = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
TIMESHIFT_DIR = os.path.join(_XDG_CACHE, "omarchy", "tv", "timeshift")
TIMESHIFT_FILE = os.path.join(TIMESHIFT_DIR, "live.ts")
TIMESHIFT_NEXT_FILE = os.path.join(TIMESHIFT_DIR, "live.next.ts")
TIMESHIFT_ACTIVE_PATH = os.path.join(CONFIG_DIR, "timeshift_active.json")
TUNE_STATUS_PATH = os.path.join(CONFIG_DIR, "tune_status.json")


def ensure_private_dir(path: str) -> str:
    """Creates path as 0700. chmod again if it already existed with a looser mode."""
    os.makedirs(path, mode=DIR_PRIVATE, exist_ok=True)
    try:
        os.chmod(path, DIR_PRIVATE)
    except OSError:
        pass
    return path


def chmod_private_file(path: str) -> None:
    """Best-effort 0600 on a dump, recording, or log the process just created."""
    try:
        os.chmod(path, FILE_PRIVATE)
    except OSError:
        pass


def touch_private_file(path: str) -> None:
    """Creates an empty 0600 file if missing so mpv inherits the mode."""
    try:
        fd = os.open(path, os.O_CREAT | os.O_WRONLY, FILE_PRIVATE)
        os.close(fd)
    except OSError:
        return
    chmod_private_file(path)


def own_scope(cmd: List[str]) -> List[str]:
    """Run cmd in its own systemd user scope, same pid.

    The record timer is a oneshot service. When it exits, systemd kills every
    process it started, recorders included, whatever their session.
    """
    runtime = os.environ.get("XDG_RUNTIME_DIR") or ""
    if not shutil.which("systemd-run") or not os.path.exists(os.path.join(runtime, "systemd", "private")):
        return list(cmd)
    return ["systemd-run", "--user", "--scope", "--quiet", "--collect", "--"] + list(cmd)


def get_runtime_socket(name: str) -> str:
    """
    Returns a UNIX socket path inside $XDG_RUNTIME_DIR (0700, owned by $USER).
    Refuses /tmp. Refuses a missing or world-accessible runtime dir.
    """
    if not name or os.path.sep in name or name in (".", ".."):
        raise ValueError("socket name must be a basename")

    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime_dir or not os.path.isdir(runtime_dir):
        raise RuntimeError(
            "XDG_RUNTIME_DIR is unset or not a directory; refusing /tmp sockets"
        )
    try:
        st = os.stat(runtime_dir)
    except OSError as exc:
        raise RuntimeError(f"cannot stat XDG_RUNTIME_DIR: {exc}") from exc
    if st.st_uid != os.getuid():
        raise RuntimeError("XDG_RUNTIME_DIR is not owned by this user")
    if (st.st_mode & 0o077) != 0:
        raise RuntimeError("XDG_RUNTIME_DIR must not be group or world accessible")
    return os.path.join(runtime_dir, name)


TUNER1_LOCK_KEY = "tuner1"

_lock_depth = threading.local()


@contextlib.contextmanager
def state_lock(key: str, timeout: Optional[float] = None) -> Iterator[None]:
    """One process at a time for key: a state file path, or a name like "tuner1".

    Nests inside one thread. Raises TimeoutError after timeout seconds.
    """
    name = "omarchy-tv-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16] + ".flock"
    held = getattr(_lock_depth, "held", None)
    if held is None:
        held = _lock_depth.held = {}
    if held.get(name):
        held[name] += 1
        try:
            yield
        finally:
            held[name] -= 1
        return
    fd = os.open(get_runtime_socket(name), os.O_CREAT | os.O_RDWR, FILE_PRIVATE)
    try:
        if timeout is None:
            fcntl.flock(fd, fcntl.LOCK_EX)
        else:
            deadline = time.time() + timeout
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.time() >= deadline:
                        raise TimeoutError(key)
                    time.sleep(0.05)
        held[name] = 1
        try:
            yield
        finally:
            held[name] = 0
    finally:
        os.close(fd)


MPV_SOCKET_PATH = get_runtime_socket("omarchy-tv-mpv.sock")
TIMESHIFT_SOCKET_PATH = get_runtime_socket("omarchy-tv-timeshift.sock")
TIMESHIFT_NEXT_SOCKET_PATH = get_runtime_socket("omarchy-tv-timeshift-next.sock")
FOLLOW_SOCKET_PATH = get_runtime_socket("omarchy-tv-follow.sock")
FOLLOW_FIFO_PATH = get_runtime_socket("omarchy-tv-follow.fifo")
TUNE_LOCK_PATH = get_runtime_socket("omarchy-tv-tune.lock")
