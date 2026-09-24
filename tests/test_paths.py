"""
Unit tests for secure runtime socket path resolution.
"""

import os
import unittest
import tempfile
from engine.paths import (
    get_runtime_socket,
    MPV_SOCKET_PATH,
    ensure_private_dir,
    chmod_private_file,
    touch_private_file,
    DIR_PRIVATE,
    FILE_PRIVATE,
)


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

    def test_fallback_socket_is_refused(self):
        old_xdg = os.environ.get("XDG_RUNTIME_DIR")
        try:
            os.environ.pop("XDG_RUNTIME_DIR", None)
            with self.assertRaises(RuntimeError):
                get_runtime_socket("fallback.sock")
        finally:
            if old_xdg is not None:
                os.environ["XDG_RUNTIME_DIR"] = old_xdg
            else:
                os.environ.pop("XDG_RUNTIME_DIR", None)

    def test_world_accessible_runtime_dir_is_refused(self):
        old_xdg = os.environ.get("XDG_RUNTIME_DIR")
        with tempfile.TemporaryDirectory() as temp_dir:
            os.chmod(temp_dir, 0o777)
            try:
                os.environ["XDG_RUNTIME_DIR"] = temp_dir
                with self.assertRaises(RuntimeError):
                    get_runtime_socket("open.sock")
            finally:
                if old_xdg is not None:
                    os.environ["XDG_RUNTIME_DIR"] = old_xdg
                else:
                    os.environ.pop("XDG_RUNTIME_DIR", None)
            os.chmod(temp_dir, 0o700)

    def test_socket_name_must_be_basename(self):
        with self.assertRaises(ValueError):
            get_runtime_socket("../escape.sock")
        with self.assertRaises(ValueError):
            get_runtime_socket("a/b.sock")

    def test_socket_constants(self):
        self.assertTrue(MPV_SOCKET_PATH.endswith("omarchy-tv-mpv.sock"))
        from engine.paths import RECORDINGS_ACTIVE_PATH, PLAYER_STATE_PATH, UI_PREFS_PATH, STATION_MAP_PATH, RECORDINGS_INDEX_PATH, TIMESHIFT_DIR, TIMESHIFT_FILE, TIMESHIFT_ACTIVE_PATH, TIMESHIFT_SOCKET_PATH, FOLLOW_SOCKET_PATH, FOLLOW_FIFO_PATH, TUNE_LOCK_PATH
        self.assertTrue(RECORDINGS_ACTIVE_PATH.endswith("recordings_active.json"))
        self.assertTrue(PLAYER_STATE_PATH.endswith("player_state.json"))
        self.assertTrue(UI_PREFS_PATH.endswith("ui_prefs.json"))
        self.assertTrue(STATION_MAP_PATH.endswith("station_map.json"))
        self.assertTrue(RECORDINGS_INDEX_PATH.endswith("recordings.json"))
        self.assertTrue(TIMESHIFT_DIR.endswith("timeshift"))
        self.assertTrue(TIMESHIFT_FILE.endswith("live.ts"))
        self.assertTrue(TIMESHIFT_ACTIVE_PATH.endswith("timeshift_active.json"))
        self.assertTrue(TIMESHIFT_SOCKET_PATH.endswith("omarchy-tv-timeshift.sock"))
        self.assertTrue(FOLLOW_SOCKET_PATH.endswith("omarchy-tv-follow.sock"))
        self.assertTrue(FOLLOW_FIFO_PATH.endswith("omarchy-tv-follow.fifo"))
        self.assertTrue(TUNE_LOCK_PATH.endswith("omarchy-tv-tune.lock"))

    def test_ensure_private_dir_tightens_mode(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            nested = os.path.join(tmp_dir, "timeshift")
            os.makedirs(nested, mode=0o755)
            os.chmod(nested, 0o755)
            ensure_private_dir(nested)
            self.assertEqual(os.stat(nested).st_mode & 0o777, DIR_PRIVATE)
            dump = os.path.join(nested, "live.ts")
            touch_private_file(dump)
            self.assertEqual(os.stat(dump).st_mode & 0o777, FILE_PRIVATE)
            os.chmod(dump, 0o644)
            chmod_private_file(dump)
            self.assertEqual(os.stat(dump).st_mode & 0o777, FILE_PRIVATE)


if __name__ == "__main__":
    unittest.main()
