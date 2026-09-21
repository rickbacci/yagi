"""Live pause buffer: growing MPEG-TS dump, not dvb:// cache."""

import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from engine.timeshift import Timeshift, is_timeshift_path


class TestTimeshift(unittest.TestCase):
    def test_ensure_dir_creates_cache(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch("engine.timeshift.TIMESHIFT_DIR", tmp_dir):
                path = Timeshift.ensure_dir()
                self.assertEqual(path, tmp_dir)
                self.assertTrue(os.path.isdir(tmp_dir))

    def test_wipe_removes_cache_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            junk = os.path.join(tmp_dir, "live.ts")
            nested = os.path.join(tmp_dir, "sub")
            os.makedirs(nested)
            with open(junk, "wb") as f:
                f.write(b"x")
            with open(os.path.join(nested, "part"), "wb") as f:
                f.write(b"y")
            with patch("engine.timeshift.TIMESHIFT_DIR", tmp_dir):
                with patch.object(Timeshift, "stop_dump"):
                    Timeshift._remove_files()
            self.assertFalse(os.path.exists(junk))
            self.assertFalse(os.path.exists(nested))
            self.assertTrue(os.path.isdir(tmp_dir))

    def test_is_timeshift_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            live = os.path.join(tmp_dir, "live.ts")
            with open(live, "wb") as f:
                f.write(b"x")
            with patch("engine.timeshift.TIMESHIFT_DIR", tmp_dir):
                self.assertTrue(is_timeshift_path(live))
                self.assertFalse(is_timeshift_path("dvb://FOX"))
                self.assertFalse(is_timeshift_path("/tmp/other.ts"))

    def test_start_dump_writes_state_and_waits_for_bytes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            live = os.path.join(tmp_dir, "live.ts")
            state = os.path.join(tmp_dir, "timeshift_active.json")
            sock = os.path.join(tmp_dir, "dump.sock")

            proc = MagicMock()
            proc.pid = 4242
            proc.poll.return_value = None

            def fake_popen(*_args, **_kwargs):
                with open(live, "wb") as f:
                    f.write(b"x" * (256 * 1024))
                return proc

            with patch("engine.timeshift.TIMESHIFT_DIR", tmp_dir), \
                 patch("engine.timeshift.TIMESHIFT_FILE", live), \
                 patch("engine.timeshift.TIMESHIFT_ACTIVE_PATH", state), \
                 patch("engine.timeshift.TIMESHIFT_SOCKET_PATH", sock), \
                 patch("engine.timeshift.MPV_CHANNELS_CONF", os.path.join(tmp_dir, "channels.conf")), \
                 patch("engine.tuner.TunerManager.get_available_tuner") as mock_tuner, \
                 patch.object(Timeshift, "_wait_frontend_free"), \
                 patch("subprocess.Popen", side_effect=fake_popen) as mock_popen:
                mock_tuner.return_value = MagicMock(adapter_id=0)
                path = Timeshift.start_dump("FOX")
                self.assertEqual(path, live)
                cmd = mock_popen.call_args[0][0]
                self.assertIn("--stream-dump=" + live, cmd)
                self.assertIn("dvb://FOX", cmd)
                self.assertIn("--dvbin-card=0", cmd)
                self.assertIn("--vo=null", cmd)
                data = Timeshift.load_state()
            self.assertTrue(data["running"])
            self.assertEqual(data["tune_name"], "FOX")
            self.assertEqual(data["pid"], 4242)

    def test_follow_emits_appended_bytes(self):
        import select
        import subprocess
        import sys
        follow_py = os.path.join(
            os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
            "engine",
            "follow_ts.py",
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            live = os.path.join(tmp_dir, "live.ts")
            sock = os.path.join(tmp_dir, "follow.sock")
            packet_a = b"A" * 188
            packet_b = b"B" * 188
            with open(live, "wb") as f:
                f.write(packet_a)
            proc = subprocess.Popen(
                [sys.executable, follow_py, live, "0", sock],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            try:
                r, _, _ = select.select([proc.stdout], [], [], 2.0)
                self.assertTrue(r)
                self.assertEqual(proc.stdout.read(188), packet_a)
                with open(live, "ab") as f:
                    f.write(packet_b)
                r, _, _ = select.select([proc.stdout], [], [], 2.0)
                self.assertTrue(r)
                self.assertEqual(proc.stdout.read(188), packet_b)
            finally:
                if proc.stdout:
                    try:
                        proc.stdout.close()
                    except OSError:
                        pass
                proc.kill()
                proc.wait(timeout=1)

    def test_align_ts_offset(self):
        from engine.follow_ts import align_ts_offset
        self.assertEqual(align_ts_offset(0), 0)
        self.assertEqual(align_ts_offset(187), 0)
        self.assertEqual(align_ts_offset(188), 188)
        self.assertEqual(align_ts_offset(200), 188)

    def test_tune_lock_tracks_this_process(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            lock = os.path.join(tmp_dir, "tune.lock")
            with patch("engine.timeshift.TUNE_LOCK_PATH", lock):
                self.assertFalse(Timeshift.tune_lock_held())
                Timeshift.acquire_tune_lock()
                try:
                    self.assertTrue(os.path.isfile(lock))
                    self.assertTrue(Timeshift.tune_lock_held())
                finally:
                    Timeshift.release_tune_lock()
                self.assertFalse(os.path.exists(lock))
                self.assertFalse(Timeshift.tune_lock_held())

    def test_tune_lock_ignores_dead_pid(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            lock = os.path.join(tmp_dir, "tune.lock")
            with patch("engine.timeshift.TUNE_LOCK_PATH", lock):
                with open(lock, "w", encoding="utf-8") as f:
                    f.write("1")
                self.assertFalse(Timeshift.tune_lock_held())
                self.assertFalse(os.path.exists(lock))


if __name__ == "__main__":
    unittest.main()
