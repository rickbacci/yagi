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
GUIDE_JSON_PATH = os.path.join(CONFIG_DIR, "guide.json")
SCAN_STATUS_PATH = os.path.join(CONFIG_DIR, "scan_status.json")
MPV_CHANNELS_CONF = os.path.join(_XDG_CONFIG, "mpv", "channels.conf")
RECORDINGS_DIR = os.path.expanduser("~/Videos/TV")
RECORDINGS_ACTIVE_PATH = os.path.join(CONFIG_DIR, "recordings_active.json")


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
