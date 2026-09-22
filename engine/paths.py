"""
Omarchy TV - Shared Paths & Runtime Security
Centralizes configuration, socket locations, and directories with secure permissions.
"""

import os
from typing import Optional

_XDG_CONFIG = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
CONFIG_DIR = os.path.join(_XDG_CONFIG, "omarchy", "tv")
CHANNELS_JSON_PATH = os.path.join(CONFIG_DIR, "channels.json")
FAVORITES_JSON_PATH = os.path.join(CONFIG_DIR, "favorites.json")
HIDDEN_JSON_PATH = os.path.join(CONFIG_DIR, "hidden.json")
GUIDE_JSON_PATH = os.path.join(CONFIG_DIR, "guide.json")
GUIDE_HISTORY_PATH = os.path.join(CONFIG_DIR, "guide_history.json")
SCAN_STATUS_PATH = os.path.join(CONFIG_DIR, "scan_status.json")
MPV_CHANNELS_CONF = os.path.join(_XDG_CONFIG, "mpv", "channels.conf")
_XDG_VIDEOS = os.environ.get("XDG_VIDEOS_DIR") or os.path.expanduser("~/Videos")
RECORDINGS_DIR = os.path.join(_XDG_VIDEOS, "TV")
RECORDINGS_ACTIVE_PATH = os.path.join(CONFIG_DIR, "recordings_active.json")
RECORDINGS_INDEX_PATH = os.path.join(CONFIG_DIR, "recordings.json")
SCHEDULE_PATH = os.path.join(CONFIG_DIR, "schedule.json")
PLAYER_STATE_PATH = os.path.join(CONFIG_DIR, "player_state.json")
UI_PREFS_PATH = os.path.join(CONFIG_DIR, "ui_prefs.json")
_XDG_CACHE = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
TIMESHIFT_DIR = os.path.join(_XDG_CACHE, "omarchy", "tv", "timeshift")
TIMESHIFT_FILE = os.path.join(TIMESHIFT_DIR, "live.ts")
TIMESHIFT_NEXT_FILE = os.path.join(TIMESHIFT_DIR, "live.next.ts")
TIMESHIFT_ACTIVE_PATH = os.path.join(CONFIG_DIR, "timeshift_active.json")
TUNE_STATUS_PATH = os.path.join(CONFIG_DIR, "tune_status.json")


def get_runtime_socket(name: str) -> str:
    """
    Returns a secure UNIX socket path inside $XDG_RUNTIME_DIR (mode 0700).
    Falls back to a private user directory in /tmp if XDG_RUNTIME_DIR is absent.
    """
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir and os.path.isdir(runtime_dir):
        return os.path.join(runtime_dir, name)

    uid = os.getuid()
    fallback_dir = os.path.join("/tmp", f"omarchy-tv-{uid}")
    os.makedirs(fallback_dir, mode=0o700, exist_ok=True)
    return os.path.join(fallback_dir, name)


MPV_SOCKET_PATH = get_runtime_socket("omarchy-tv-mpv.sock")
DAEMON_SOCKET_PATH = get_runtime_socket("omarchy-tv-daemon.sock")
TIMESHIFT_SOCKET_PATH = get_runtime_socket("omarchy-tv-timeshift.sock")
TIMESHIFT_NEXT_SOCKET_PATH = get_runtime_socket("omarchy-tv-timeshift-next.sock")
FOLLOW_SOCKET_PATH = get_runtime_socket("omarchy-tv-follow.sock")
FOLLOW_FIFO_PATH = get_runtime_socket("omarchy-tv-follow.fifo")
TUNE_LOCK_PATH = get_runtime_socket("omarchy-tv-tune.lock")
