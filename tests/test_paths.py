"""
Unit tests for secure runtime socket path resolution.
"""

import os
import unittest
import tempfile
from engine.paths import get_runtime_socket, MPV_SOCKET_PATH, DAEMON_SOCKET_PATH


class TestPathsSecurity(unittest.TestCase):
    def test_xdg_runtime_socket(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            old_xdg = os.environ.get("XDG_RUNTIME_DIR")
            try:
                os.environ["XDG_RUNTIME_DIR"] = temp_dir
                sock_path = get_runtime_socket("test.sock")
                self.assertTrue(sock_path.startswith(temp_dir))
                self.assertEqual(sock_path, os.path.join(temp_dir, "test.sock"))
            finally:
                if old_xdg is not None:
                    os.environ["XDG_RUNTIME_DIR"] = old_xdg
                else:
                    os.environ.pop("XDG_RUNTIME_DIR", None)

    def test_fallback_socket_permissions(self):
        old_xdg = os.environ.get("XDG_RUNTIME_DIR")
        try:
            os.environ.pop("XDG_RUNTIME_DIR", None)
            sock_path = get_runtime_socket("fallback.sock")
            parent_dir = os.path.dirname(sock_path)
            self.assertTrue(os.path.isdir(parent_dir))
            # Must be mode 0700 (private to user)
            mode = os.stat(parent_dir).st_mode & 0o777
            self.assertEqual(mode, 0o700, f"Fallback dir {parent_dir} must be mode 0700")
        finally:
            if old_xdg is not None:
                os.environ["XDG_RUNTIME_DIR"] = old_xdg

    def test_socket_constants(self):
        self.assertTrue(MPV_SOCKET_PATH.endswith("omarchy-tv-mpv.sock"))
        self.assertTrue(DAEMON_SOCKET_PATH.endswith("omarchy-tv-daemon.sock"))
        from engine.paths import RECORDINGS_ACTIVE_PATH, PLAYER_STATE_PATH, UI_PREFS_PATH, RECORDINGS_INDEX_PATH, TIMESHIFT_DIR, TIMESHIFT_ACTIVE_PATH
        self.assertTrue(RECORDINGS_ACTIVE_PATH.endswith("recordings_active.json"))
        self.assertTrue(PLAYER_STATE_PATH.endswith("player_state.json"))
        self.assertTrue(UI_PREFS_PATH.endswith("ui_prefs.json"))
        self.assertTrue(RECORDINGS_INDEX_PATH.endswith("recordings.json"))
        self.assertTrue(TIMESHIFT_DIR.endswith("timeshift"))
        self.assertTrue(TIMESHIFT_ACTIVE_PATH.endswith("timeshift_active.json"))


if __name__ == "__main__":
    unittest.main()
