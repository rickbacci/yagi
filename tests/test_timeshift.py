"""Live pause buffer: growing MPEG-TS dump, not dvb:// cache."""

import os
import socket
import tempfile
import time
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
                self.assertTrue(any(str(a).startswith("--log-file=") for a in cmd))
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

    def test_follow_reopens_replaced_file(self):
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
            packet_c = b"C" * 188
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
                os.remove(live)
                deadline = time.time() + 2.0
                while time.time() < deadline and not os.path.exists(sock):
                    time.sleep(0.02)
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.settimeout(1.0)
                    s.connect(sock)
                    s.sendall(b"REOPEN\n")
                with open(live, "wb") as f:
                    f.write(packet_c)
                r, _, _ = select.select([proc.stdout], [], [], 2.0)
                self.assertTrue(r)
                self.assertEqual(proc.stdout.read(188), packet_c)
            finally:
                if proc.stdout:
                    try:
                        proc.stdout.close()
                    except OSError:
                        pass
                proc.kill()
                proc.wait(timeout=1)

    def test_follow_pos_reports_cursor(self):
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
                deadline = time.time() + 2.0
                while time.time() < deadline and not os.path.exists(sock):
                    time.sleep(0.02)
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.settimeout(1.0)
                    s.connect(sock)
                    s.sendall(b"POS")
                    pos = int(s.recv(64))
                self.assertEqual(pos, 188)
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.settimeout(1.0)
                    s.connect(sock)
                    s.sendall(b"SEEK 0")
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.settimeout(1.0)
                    s.connect(sock)
                    s.sendall(b"POS")
                    pos = int(s.recv(64))
                self.assertEqual(pos, 0)
            finally:
                if proc.stdout:
                    try:
                        proc.stdout.close()
                    except OSError:
                        pass
                proc.kill()
                proc.wait(timeout=1)

    def test_follow_pace_and_catchup_commands(self):
        from engine.follow_ts import TsFollower
        follower = TsFollower("/tmp/x.ts", 0, "/tmp/x.sock")
        follower._handle_ctl("PACE 500000")
        self.assertTrue(follower._paced)
        self.assertEqual(follower._pace_bps, 500000.0)
        follower._handle_ctl("CATCHUP")
        self.assertFalse(follower._paced)

    def test_follow_pace_wait_sleeps_when_ahead(self):
        from engine.follow_ts import TsFollower
        follower = TsFollower("/tmp/x.ts", 0, "/tmp/x.sock")
        follower._paced = True
        follower._pace_bps = 10000
        follower._pace_origin_t = time.monotonic()
        follower._pace_origin_pos = 0
        follower.pos = 20000
        t0 = time.monotonic()
        follower._pace_wait()
        self.assertGreaterEqual(time.monotonic() - t0, 0.2)

    def test_start_dump_keep_follow_does_not_wipe_follow(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            live = os.path.join(tmp_dir, "live.ts")
            state = os.path.join(tmp_dir, "timeshift_active.json")
            sock = os.path.join(tmp_dir, "dump.sock")
            follow_sock = os.path.join(tmp_dir, "follow.sock")
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
                 patch("engine.timeshift.FOLLOW_SOCKET_PATH", follow_sock), \
                 patch("engine.timeshift.MPV_CHANNELS_CONF", os.path.join(tmp_dir, "channels.conf")), \
                 patch("engine.tuner.TunerManager.get_available_tuner") as mock_tuner, \
                 patch.object(Timeshift, "_wait_frontend_free"), \
                 patch.object(Timeshift, "send_follow_reopen", return_value=True), \
                 patch.object(Timeshift, "wipe") as mock_wipe, \
                 patch.object(Timeshift, "stop_follow") as mock_stop_follow, \
                 patch("subprocess.Popen", side_effect=fake_popen):
                mock_tuner.return_value = MagicMock(adapter_id=0)
                Timeshift._write_state({
                    "running": True,
                    "pid": 999999,
                    "follow_pid": 777777,
                    "follow_socket": follow_sock,
                })
                path = Timeshift.start_dump("FOX", keep_follow=True)
                self.assertEqual(path, live)
                mock_wipe.assert_not_called()
                mock_stop_follow.assert_not_called()
                data = Timeshift.load_state()
            self.assertEqual(data["follow_pid"], 777777)
            self.assertEqual(data["tune_name"], "FOX")

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
                self.assertTrue(Timeshift.acquire_tune_lock())
                try:
                    self.assertTrue(os.path.isfile(lock))
                    self.assertTrue(Timeshift.tune_lock_held())
                finally:
                    Timeshift.release_tune_lock()
                self.assertFalse(os.path.exists(lock))
                self.assertFalse(Timeshift.tune_lock_held())

    def test_tune_lock_rejects_second_holder(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            lock = os.path.join(tmp_dir, "tune.lock")
            with patch("engine.timeshift.TUNE_LOCK_PATH", lock):
                self.assertTrue(Timeshift.acquire_tune_lock())
                try:
                    self.assertFalse(Timeshift.acquire_tune_lock())
                finally:
                    Timeshift.release_tune_lock()

    def test_tune_lock_ignores_dead_pid(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            lock = os.path.join(tmp_dir, "tune.lock")
            with patch("engine.timeshift.TUNE_LOCK_PATH", lock):
                with open(lock, "w", encoding="utf-8") as f:
                    f.write("1")
                self.assertFalse(Timeshift.tune_lock_held())
                self.assertFalse(os.path.exists(lock))

    def test_retune_keep_window_locks_next_on_free_tuner(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            live = os.path.join(tmp_dir, "live.ts")
            nxt = os.path.join(tmp_dir, "live.next.ts")
            state = os.path.join(tmp_dir, "timeshift_active.json")
            sock = os.path.join(tmp_dir, "dump.sock")
            next_sock = os.path.join(tmp_dir, "dump-next.sock")
            follow_sock = os.path.join(tmp_dir, "follow.sock")
            proc = MagicMock()
            proc.pid = 8888
            proc.poll.return_value = None

            def fake_popen(*_args, **_kwargs):
                with open(nxt, "wb") as f:
                    f.write(b"x" * (256 * 1024))
                return proc

            with patch("engine.timeshift.TIMESHIFT_DIR", tmp_dir), \
                 patch("engine.timeshift.TIMESHIFT_FILE", live), \
                 patch("engine.timeshift.TIMESHIFT_NEXT_FILE", nxt), \
                 patch("engine.timeshift.TIMESHIFT_ACTIVE_PATH", state), \
                 patch("engine.timeshift.TIMESHIFT_SOCKET_PATH", sock), \
                 patch("engine.timeshift.TIMESHIFT_NEXT_SOCKET_PATH", next_sock), \
                 patch("engine.timeshift.FOLLOW_SOCKET_PATH", follow_sock), \
                 patch("engine.timeshift.MPV_CHANNELS_CONF", os.path.join(tmp_dir, "channels.conf")), \
                 patch("engine.tuner.TunerManager.get_available_tuner") as mock_tuner, \
                 patch.object(Timeshift, "send_follow_pause", return_value=True), \
                 patch.object(Timeshift, "stop_dump"), \
                 patch("subprocess.Popen", side_effect=fake_popen):
                mock_tuner.return_value = MagicMock(adapter_id=1)
                Timeshift._write_state({
                    "running": True,
                    "pid": 1111,
                    "adapter_id": 0,
                    "follow_pid": 2222,
                    "follow_socket": follow_sock,
                })
                with open(live, "wb") as f:
                    f.write(b"old")
                path = Timeshift.retune_keep_window("FOX")
                self.assertEqual(path, live)
                self.assertTrue(os.path.isfile(live))
                self.assertFalse(os.path.exists(nxt))
                data = Timeshift.load_state()
            self.assertEqual(data["adapter_id"], 1)
            self.assertEqual(data["pid"], 8888)
            self.assertEqual(data["tune_name"], "FOX")
            self.assertEqual(data["follow_pid"], 2222)
            self.assertEqual(data["socket"], next_sock)

    def test_retune_keep_window_does_not_reuse_live_dump_socket(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            live = os.path.join(tmp_dir, "live.ts")
            nxt = os.path.join(tmp_dir, "live.next.ts")
            state = os.path.join(tmp_dir, "timeshift_active.json")
            sock = os.path.join(tmp_dir, "dump.sock")
            next_sock = os.path.join(tmp_dir, "dump-next.sock")
            follow_sock = os.path.join(tmp_dir, "follow.sock")
            proc = MagicMock()
            proc.pid = 9999
            proc.poll.return_value = None

            def fake_popen(*_args, **_kwargs):
                with open(nxt, "wb") as f:
                    f.write(b"x" * (256 * 1024))
                return proc

            with patch("engine.timeshift.TIMESHIFT_DIR", tmp_dir), \
                 patch("engine.timeshift.TIMESHIFT_FILE", live), \
                 patch("engine.timeshift.TIMESHIFT_NEXT_FILE", nxt), \
                 patch("engine.timeshift.TIMESHIFT_ACTIVE_PATH", state), \
                 patch("engine.timeshift.TIMESHIFT_SOCKET_PATH", sock), \
                 patch("engine.timeshift.TIMESHIFT_NEXT_SOCKET_PATH", next_sock), \
                 patch("engine.timeshift.FOLLOW_SOCKET_PATH", follow_sock), \
                 patch("engine.timeshift.MPV_CHANNELS_CONF", os.path.join(tmp_dir, "channels.conf")), \
                 patch("engine.tuner.TunerManager.get_available_tuner") as mock_tuner, \
                 patch.object(Timeshift, "send_follow_pause", return_value=True), \
                 patch.object(Timeshift, "stop_dump"), \
                 patch("subprocess.Popen", side_effect=fake_popen):
                mock_tuner.return_value = MagicMock(adapter_id=1)
                Timeshift._write_state({
                    "running": True,
                    "pid": 1111,
                    "adapter_id": 0,
                    "socket": next_sock,
                    "follow_pid": 2222,
                    "follow_socket": follow_sock,
                })
                with open(live, "wb") as f:
                    f.write(b"old")
                path = Timeshift.retune_keep_window("NBC")
                self.assertEqual(path, live)
                data = Timeshift.load_state()
            self.assertEqual(data["socket"], sock)
            self.assertEqual(data["pid"], 9999)


if __name__ == "__main__":
    unittest.main()
