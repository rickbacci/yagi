"""Live pause buffer: growing MPEG-TS dump, not dvb:// cache."""

import json
import os
import signal
import socket
import stat
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, MagicMock

from engine.timeshift import ATSC_BPS, LIVE_SLACK, SEEK_STEP, Timeshift, align_ts, is_timeshift_path


class TestTimeshift(unittest.TestCase):
    def test_ensure_dir_creates_cache(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch("engine.timeshift.TIMESHIFT_DIR", tmp_dir):
                path = Timeshift.ensure_dir()
                self.assertEqual(path, tmp_dir)
                self.assertTrue(os.path.isdir(tmp_dir))
                self.assertEqual(os.stat(tmp_dir).st_mode & 0o777, 0o700)

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

    def test_remove_files_keeps_the_two_logs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            for name in ("hud.log", "dump.log", "dump-next.log", "live.ts"):
                with open(os.path.join(tmp_dir, name), "wb") as f:
                    f.write(b"x")
            with patch("engine.timeshift.TIMESHIFT_DIR", tmp_dir):
                Timeshift._remove_files()
            self.assertTrue(os.path.exists(os.path.join(tmp_dir, "hud.log")))
            self.assertTrue(os.path.exists(os.path.join(tmp_dir, "dump.log")))
            self.assertFalse(os.path.exists(os.path.join(tmp_dir, "dump-next.log")))
            self.assertFalse(os.path.exists(os.path.join(tmp_dir, "live.ts")))

    def test_is_timeshift_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            live = os.path.join(tmp_dir, "live.ts")
            with open(live, "wb") as f:
                f.write(b"x")
            with patch("engine.timeshift.TIMESHIFT_DIR", tmp_dir):
                self.assertTrue(is_timeshift_path(live))
                self.assertFalse(is_timeshift_path("dvb://FOX"))
                self.assertFalse(is_timeshift_path("/tmp/other.ts"))

    def test_fwd_hop_last_step_is_live(self):
        self.assertEqual(Timeshift.fwd_hop(LIVE_SLACK), 0.0)
        self.assertEqual(Timeshift.fwd_hop(SEEK_STEP), 0.0)
        self.assertEqual(Timeshift.fwd_hop(SEEK_STEP + 0.1), SEEK_STEP)
        self.assertEqual(Timeshift.fwd_hop(90.0), SEEK_STEP)

    def test_live_join_sits_back_from_the_torn_packet(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            live = os.path.join(tmp_dir, "live.ts")
            with open(live, "wb") as handle:
                handle.truncate(2 * 1024 * 1024)
            with patch("engine.timeshift.TIMESHIFT_FILE", live):
                join = Timeshift.live_join_byte()
                edge = Timeshift.live_edge_byte()
            self.assertLess(join, edge)
            self.assertEqual(join, ((2 * 1024 * 1024) - 512 * 1024) // 188 * 188)

    def test_delay_sec_pause_and_play_share_the_gap(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            live = os.path.join(tmp_dir, "live.ts")
            state = os.path.join(tmp_dir, "timeshift_active.json")
            size = 20_000_000
            rate = 2_000_000
            with open(live, "wb") as f:
                f.write(b"x" * size)
            with patch("engine.timeshift.TIMESHIFT_FILE", live), \
                 patch("engine.timeshift.TIMESHIFT_ACTIVE_PATH", state), \
                 patch("engine.timeshift.TIMESHIFT_DIR", tmp_dir):
                Timeshift.patch_state(
                    view="delayed",
                    paused=True,
                    playhead_byte=0,
                    mux_bps=rate,
                )
                paused_delay = Timeshift.delay_sec()
                Timeshift.patch_state(paused=False, view="delayed")
                playing_delay = Timeshift.delay_sec()
            self.assertAlmostEqual(paused_delay, size / rate, delta=0.05)
            self.assertAlmostEqual(paused_delay, playing_delay, delta=0.01)

    def test_hold_dump_stops_an_hour_past_the_playhead(self):
        self.assertEqual(Timeshift.pause_cap_bytes(), int(ATSC_BPS / 8.0 * 3600))
        with tempfile.TemporaryDirectory() as tmp_dir:
            live = os.path.join(tmp_dir, "live.ts")
            state_path = os.path.join(tmp_dir, "timeshift_active.json")
            playhead = 1880
            cap = 1880
            with open(live, "wb") as f:
                f.write(b"x" * (playhead + cap))
            sock = os.path.join(tmp_dir, "missing.sock")
            with patch("engine.timeshift.TIMESHIFT_FILE", live), \
                 patch("engine.timeshift.TIMESHIFT_ACTIVE_PATH", state_path), \
                 patch("engine.timeshift.TIMESHIFT_DIR", tmp_dir), \
                 patch("engine.timeshift.TIMESHIFT_SOCKET_PATH", sock), \
                 patch.object(Timeshift, "pause_cap_bytes", return_value=cap), \
                 patch.object(Timeshift, "_pid_alive", return_value=True), \
                 patch("os.kill") as kill:
                Timeshift.patch_state(
                    running=True,
                    paused=True,
                    pid=4242,
                    playhead_byte=playhead,
                    playhead_t=time.time() - 10,
                    view="live",
                    tune_name="WEWSHD",
                    http_pid=7,
                    http_port=9,
                )
                self.assertTrue(Timeshift.hold_dump_if_full())
                state = Timeshift.load_state()
                self.assertTrue(state.get("dump_held"))
                self.assertEqual(state.get("pid"), 0)
                self.assertEqual(state.get("playhead_byte"), playhead)
                self.assertTrue(state.get("paused"))
                self.assertEqual(state.get("tune_name"), "WEWSHD")
                self.assertEqual(state.get("http_pid"), 7)
            kill.assert_called_with(4242, signal.SIGTERM)
            self.assertTrue(os.path.isfile(live))
            with patch("engine.timeshift.TIMESHIFT_FILE", live), \
                 patch("engine.timeshift.TIMESHIFT_ACTIVE_PATH", state_path), \
                 patch("engine.timeshift.TIMESHIFT_DIR", tmp_dir):
                self.assertFalse(Timeshift.hold_dump_if_full())
                delay = Timeshift.delay_sec()
            self.assertAlmostEqual(delay, cap / (ATSC_BPS / 8.0), delta=0.01)

    def test_hold_dump_leaves_live_playback_writing(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            live = os.path.join(tmp_dir, "live.ts")
            state_path = os.path.join(tmp_dir, "timeshift_active.json")
            with open(live, "wb") as f:
                f.write(b"x" * 188000)
            with patch("engine.timeshift.TIMESHIFT_FILE", live), \
                 patch("engine.timeshift.TIMESHIFT_ACTIVE_PATH", state_path), \
                 patch("engine.timeshift.TIMESHIFT_DIR", tmp_dir), \
                 patch.object(Timeshift, "pause_cap_bytes", return_value=1880), \
                 patch.object(Timeshift, "_pid_alive", return_value=True), \
                 patch("os.kill") as kill:
                Timeshift.patch_state(
                    running=True,
                    paused=False,
                    view="live",
                    pid=4242,
                    playhead_byte=0,
                )
                self.assertFalse(Timeshift.hold_dump_if_full())
            kill.assert_not_called()

    def test_hold_dump_stops_live_playback_when_the_disk_is_low(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            live = os.path.join(tmp_dir, "live.ts")
            state_path = os.path.join(tmp_dir, "timeshift_active.json")
            with open(live, "wb") as f:
                f.write(b"x" * 1880)
            with patch("engine.timeshift.TIMESHIFT_FILE", live), \
                 patch("engine.timeshift.TIMESHIFT_ACTIVE_PATH", state_path), \
                 patch("engine.timeshift.TIMESHIFT_DIR", tmp_dir), \
                 patch("engine.dvr.disk_below_floor", return_value=True), \
                 patch.object(Timeshift, "_pid_alive", return_value=True), \
                 patch("os.kill") as kill:
                Timeshift.patch_state(
                    running=True,
                    paused=False,
                    view="live",
                    pid=4242,
                    playhead_byte=0,
                    socket=os.path.join(tmp_dir, "no.sock"),
                )
                self.assertTrue(Timeshift.hold_dump_if_full())
                self.assertEqual(Timeshift.load_state().get("dump_held"), "disk")
            kill.assert_called_with(4242, signal.SIGTERM)
            self.assertTrue(os.path.isfile(live))

    def test_hold_dump_leaves_a_shorter_pause_writing(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            live = os.path.join(tmp_dir, "live.ts")
            state_path = os.path.join(tmp_dir, "timeshift_active.json")
            with open(live, "wb") as f:
                f.write(b"x" * 18800)
            with patch("engine.timeshift.TIMESHIFT_FILE", live), \
                 patch("engine.timeshift.TIMESHIFT_ACTIVE_PATH", state_path), \
                 patch("engine.timeshift.TIMESHIFT_DIR", tmp_dir), \
                 patch.object(Timeshift, "_pid_alive", return_value=True), \
                 patch("os.kill") as kill:
                Timeshift.patch_state(
                    running=True,
                    paused=True,
                    pid=4242,
                    playhead_byte=0,
                    playhead_t=time.time(),
                    view="live",
                )
                self.assertFalse(Timeshift.hold_dump_if_full())
            kill.assert_not_called()
            self.assertFalse(Timeshift.load_state().get("dump_held"))

    def test_delay_sec_live_unpaused_is_zero(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            state = os.path.join(tmp_dir, "timeshift_active.json")
            with patch("engine.timeshift.TIMESHIFT_ACTIVE_PATH", state):
                Timeshift.patch_state(view="live", paused=False, playhead_t=time.time() - 30)
                self.assertEqual(Timeshift.delay_sec(), 0.0)

    def test_delay_sec_leaves_out_the_tune_lag(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            live = os.path.join(tmp_dir, "live.ts")
            state = os.path.join(tmp_dir, "timeshift_active.json")
            with open(live, "wb") as f:
                f.write(b"x" * (188 * 100_000))
            with patch("engine.timeshift.TIMESHIFT_FILE", live), \
                 patch("engine.timeshift.TIMESHIFT_ACTIVE_PATH", state), \
                 patch("engine.timeshift.TIMESHIFT_DIR", tmp_dir), \
                 patch.object(Timeshift, "write_rate", return_value=188 * 1000), \
                 patch.object(Timeshift, "follow_pos", return_value=None):
                Timeshift.patch_state(view="live", paused=True, playhead_byte=188 * 90_000, live_lag=188 * 6_000)
                self.assertAlmostEqual(Timeshift.delay_sec(), 4.0, places=2)
                Timeshift.patch_state(live_lag=0)
                self.assertAlmostEqual(Timeshift.delay_sec(), 10.0, places=2)

    def test_write_rate_uses_dump_growth_paused_or_not(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            live = os.path.join(tmp_dir, "live.ts")
            state = os.path.join(tmp_dir, "timeshift_active.json")
            mark = 1880
            grown = 5_000_000
            with open(live, "wb") as f:
                f.write(b"x" * (mark + grown))
            t0 = time.time() - 10.0
            with patch("engine.timeshift.TIMESHIFT_FILE", live), \
                 patch("engine.timeshift.TIMESHIFT_ACTIVE_PATH", state), \
                 patch("engine.timeshift.TIMESHIFT_DIR", tmp_dir):
                for paused in (True, False):
                    Timeshift.patch_state(
                        paused=paused,
                        playhead_byte=0,
                        rate_byte=mark,
                        rate_t=t0,
                        mux_bps=0,
                    )
                    rate = Timeshift.write_rate()
                    self.assertAlmostEqual(rate, grown / 10.0, delta=50_000)
                    self.assertNotAlmostEqual(rate, ATSC_BPS / 8.0, delta=100_000)

    def test_write_rate_nudges_a_known_mux(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            live = os.path.join(tmp_dir, "live.ts")
            state = os.path.join(tmp_dir, "timeshift_active.json")
            mark = 1880
            with open(live, "wb") as f:
                f.write(b"x" * (mark + 12_000_000))
            with patch("engine.timeshift.TIMESHIFT_FILE", live), \
                 patch("engine.timeshift.TIMESHIFT_ACTIVE_PATH", state), \
                 patch("engine.timeshift.TIMESHIFT_DIR", tmp_dir):
                Timeshift.patch_state(
                    rate_byte=mark,
                    rate_t=time.time() - 10.0,
                    mux_bps=800_000,
                )
                rate = Timeshift.write_rate()
            self.assertGreater(rate, 800_000)
            self.assertLess(rate, 900_000)

    def test_write_rate_keeps_mux_through_a_stall(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            live = os.path.join(tmp_dir, "live.ts")
            state = os.path.join(tmp_dir, "timeshift_active.json")
            mark = 1880
            with open(live, "wb") as f:
                f.write(b"x" * (mark + 20_000))
            with patch("engine.timeshift.TIMESHIFT_FILE", live), \
                 patch("engine.timeshift.TIMESHIFT_ACTIVE_PATH", state), \
                 patch("engine.timeshift.TIMESHIFT_DIR", tmp_dir):
                Timeshift.patch_state(
                    rate_byte=mark,
                    rate_t=time.time() - 10.0,
                    mux_bps=800_000,
                )
                self.assertEqual(Timeshift.write_rate(), 800_000)

    def test_write_rate_replaces_a_crawling_mux(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            live = os.path.join(tmp_dir, "live.ts")
            state = os.path.join(tmp_dir, "timeshift_active.json")
            mark = 1880
            with open(live, "wb") as f:
                f.write(b"x" * (mark + 10_000_000))
            with patch("engine.timeshift.TIMESHIFT_FILE", live), \
                 patch("engine.timeshift.TIMESHIFT_ACTIVE_PATH", state), \
                 patch("engine.timeshift.TIMESHIFT_DIR", tmp_dir):
                Timeshift.patch_state(
                    rate_byte=mark,
                    rate_t=time.time() - 10.0,
                    mux_bps=7_734,
                )
                rate = Timeshift.write_rate()
            self.assertAlmostEqual(rate, 1_000_000, delta=20_000)

    def test_write_rate_ignores_a_short_spike(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            live = os.path.join(tmp_dir, "live.ts")
            state = os.path.join(tmp_dir, "timeshift_active.json")
            with open(live, "wb") as f:
                f.write(b"x" * (1880 + 8_000_000))
            with patch("engine.timeshift.TIMESHIFT_FILE", live), \
                 patch("engine.timeshift.TIMESHIFT_ACTIVE_PATH", state), \
                 patch("engine.timeshift.TIMESHIFT_DIR", tmp_dir):
                Timeshift.patch_state(
                    rate_byte=1880,
                    rate_t=time.time() - 1.0,
                    mux_bps=800_000,
                )
                self.assertEqual(Timeshift.write_rate(), 800_000)

    def test_pace_waits_out_the_whole_lead(self):
        from engine.follow_ts import TsFollower
        with tempfile.TemporaryDirectory() as tmp_dir:
            live = os.path.join(tmp_dir, "live.ts")
            with open(live, "wb") as f:
                f.write(b"x" * 188)
            follower = TsFollower(live, 0, os.path.join(tmp_dir, "follow.sock"))
            follower._paced = True
            follower._pace_bps = 1000.0
            follower._pace_origin_t = time.monotonic()
            follower._pace_origin_pos = 0
            follower.pos = 10_000
            slept = []

            def fake_sleep(seconds):
                slept.append(seconds)
                follower._pace_origin_t -= seconds

            with patch("engine.follow_ts.time.sleep", side_effect=fake_sleep):
                follower._pace_wait()
            self.assertGreater(sum(slept), 6.0)
            self.assertLess(sum(slept), 8.0)
            self.assertLess(max(slept), 0.2)

    def test_write_rate_falls_back_to_atsc_when_unpaused(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            state = os.path.join(tmp_dir, "timeshift_active.json")
            with patch("engine.timeshift.TIMESHIFT_ACTIVE_PATH", state):
                Timeshift.patch_state(paused=False, mux_bps=0, playhead_t=0)
                self.assertEqual(Timeshift.write_rate(), ATSC_BPS / 8.0)
                Timeshift.patch_state(paused=False, mux_bps=1_500_000)
                self.assertEqual(Timeshift.write_rate(), 1_500_000)

    def test_picture_opens_where_a_second_is_already_saved(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            live = os.path.join(tmp_dir, "live.ts")
            state = os.path.join(tmp_dir, "timeshift_active.json")
            with patch("engine.timeshift.TIMESHIFT_FILE", live), \
                 patch("engine.timeshift.TIMESHIFT_ACTIVE_PATH", state):
                Timeshift._write_state({"play_from": 0})
                with open(live, "wb") as f:
                    f.write(b"\x47" * (256 * 1024))
                self.assertEqual(Timeshift.picture_open_byte(), 0)
                with open(live, "wb") as f:
                    f.write(b"\x47" * (5 * 1024 * 1024))
                self.assertEqual(
                    Timeshift.picture_open_byte(),
                    align_ts(5 * 1024 * 1024 - 2 * 1024 * 1024),
                )

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
                 patch.object(Timeshift, "_wait_frontend_free"), \
                 patch("subprocess.Popen", side_effect=fake_popen) as mock_popen:
                path = Timeshift.start_dump("FOX")
                self.assertEqual(path, live)
                cmd = mock_popen.call_args[0][0]
                self.assertIn("--stream-dump=" + live, cmd)
                self.assertTrue(any(str(a).startswith("--log-file=") for a in cmd))
                self.assertIn("dvb://FOX", cmd)
                self.assertIn("--dvbin-full-transponder=yes", cmd)
                self.assertIn("--dvbin-card=0", cmd)
                self.assertIn("--vo=null", cmd)
                data = Timeshift.load_state()
            self.assertTrue(data["running"])
            self.assertEqual(data["tune_name"], "FOX")
            self.assertEqual(data["pid"], 4242)
            self.assertEqual(data["adapter_id"], 0)

    def test_broken_pipe_keeps_the_fifo(self):
        import sys
        follow_py = os.path.join(
            os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
            "engine",
            "follow_ts.py",
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            live = os.path.join(tmp_dir, "live.ts")
            sock = os.path.join(tmp_dir, "follow.sock")
            fifo = os.path.join(tmp_dir, "follow.fifo")
            packet = b"\x47" + b"\x00" * 187
            with open(live, "wb") as f:
                f.write(packet * 400)
            os.mkfifo(fifo, 0o600)
            proc = subprocess.Popen(
                [sys.executable, follow_py, live, "0", sock, fifo],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            reader = os.open(fifo, os.O_RDONLY)
            try:
                os.read(reader, 188)
                os.close(reader)
                reader = -1
                time.sleep(0.3)
                self.assertIsNone(proc.poll())
                self.assertTrue(stat.S_ISFIFO(os.stat(fifo).st_mode))
            finally:
                if reader >= 0:
                    os.close(reader)
                proc.kill()
                proc.wait(timeout=1)

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
            finally:
                if proc.stdout:
                    try:
                        proc.stdout.close()
                    except OSError:
                        pass
                proc.kill()
                proc.wait(timeout=1)

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
                 patch.object(Timeshift, "_wait_frontend_free"), \
                 patch.object(Timeshift, "send_follow_reopen", return_value=True), \
                 patch.object(Timeshift, "wipe") as mock_wipe, \
                 patch.object(Timeshift, "stop_follow") as mock_stop_follow, \
                 patch("subprocess.Popen", side_effect=fake_popen):
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

    def test_seek_cuts_at_the_next_video_keyframe(self):
        from engine.follow_ts import TsFollower, packet_is_video_keyframe
        filler = bytes([0x47, 0x00, 0x21, 0x10]) + bytes(184)
        pframe = bytearray(188)
        pframe[0] = 0x47
        pframe[1] = 0x40
        pframe[2] = 0x21
        pframe[3] = 0x10
        pframe[4:10] = b"\x00\x00\x01\x00\x00\x10"
        key = bytearray(188)
        key[0] = 0x47
        key[1] = 0x40
        key[2] = 0x21
        key[3] = 0x10
        key[4:8] = b"\x00\x00\x01\xb3"
        self.assertFalse(packet_is_video_keyframe(bytes(pframe)))
        self.assertTrue(packet_is_video_keyframe(bytes(key)))
        data = filler + bytes(pframe) + filler + bytes(key) + filler
        with tempfile.TemporaryDirectory() as tmp_dir:
            live = os.path.join(tmp_dir, "live.ts")
            sock = os.path.join(tmp_dir, "follow.sock")
            with open(live, "wb") as f:
                f.write(data)
            follower = TsFollower(live, 0, sock)
            follower._open_file()
            sentinel = os.open(os.path.join(tmp_dir, "out"), os.O_CREAT | os.O_RDWR, 0o600)
            follower._out_fd = sentinel
            try:
                follower._apply_seek(0)
                self.assertEqual(follower.pos, 188 * 3)
                self.assertTrue(follower._break)
                self.assertEqual(follower._out_fd, sentinel)
                from engine.follow_ts import mark_discontinuity, TS_PACKET
                marked = mark_discontinuity(bytes(key) + filler)
                self.assertEqual(marked[0], 0x47)
                self.assertEqual(marked[3] & 0x30, 0x20)
                self.assertEqual(marked[5] & 0x80, 0x80)
                self.assertEqual(marked[TS_PACKET:TS_PACKET + 4], bytes(key[:4]))
                follower._apply_seek(188 * 4)
                self.assertEqual(follower.pos, 188 * 4)
                self.assertEqual(follower._out_fd, sentinel)
            finally:
                os.close(sentinel)
                if follower._fd is not None:
                    os.close(follower._fd)

    def test_seek_on_junk_stays_aligned(self):
        from engine.follow_ts import TsFollower
        with tempfile.TemporaryDirectory() as tmp_dir:
            live = os.path.join(tmp_dir, "live.ts")
            sock = os.path.join(tmp_dir, "follow.sock")
            with open(live, "wb") as f:
                f.write(b"A" * 1880)
            follower = TsFollower(live, 0, sock)
            follower._open_file()
            try:
                follower._apply_seek(200)
                self.assertEqual(follower.pos, 188)
            finally:
                if follower._fd is not None:
                    os.close(follower._fd)

    def test_start_follow_detaches_onto_the_fifo(self):
        import stat as stat_mod
        with tempfile.TemporaryDirectory() as tmp_dir:
            live = os.path.join(tmp_dir, "live.ts")
            state = os.path.join(tmp_dir, "timeshift_active.json")
            sock = os.path.join(tmp_dir, "follow.sock")
            fifo = os.path.join(tmp_dir, "follow.fifo")
            with open(live, "wb") as f:
                f.write(b"x" * 188)
            proc = MagicMock()
            proc.pid = 5150
            proc.poll.return_value = None
            proc.returncode = None
            with patch("engine.timeshift.TIMESHIFT_FILE", live), \
                 patch("engine.timeshift.TIMESHIFT_ACTIVE_PATH", state), \
                 patch("engine.timeshift.TIMESHIFT_DIR", tmp_dir), \
                 patch("engine.timeshift.FOLLOW_SOCKET_PATH", sock), \
                 patch("engine.timeshift.FOLLOW_FIFO_PATH", fifo), \
                 patch("subprocess.Popen", return_value=proc) as mock_popen:
                pid = Timeshift.start_follow(188)
                self.assertEqual(pid, 5150)
                self.assertTrue(stat_mod.S_ISFIFO(os.stat(fifo).st_mode))
                cmd = mock_popen.call_args[0][0]
                kwargs = mock_popen.call_args[1]
                self.assertEqual(cmd[-1], fifo)
                self.assertEqual(cmd[-2], sock)
                self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)
                self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
                self.assertTrue(kwargs["start_new_session"])
                mock_popen.reset_mock()
                with patch.object(Timeshift, "_pid_alive", return_value=True):
                    again = Timeshift.start_follow(0)
                self.assertEqual(again, 5150)
                mock_popen.assert_not_called()

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

    def test_retune_keep_window_dumps_tuner_0(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            live = os.path.join(tmp_dir, "live.ts")
            state = os.path.join(tmp_dir, "timeshift_active.json")
            sock = os.path.join(tmp_dir, "dump.sock")
            follow_sock = os.path.join(tmp_dir, "follow.sock")
            proc = MagicMock()
            proc.pid = 8888
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
                 patch.object(Timeshift, "_wait_frontend_free"), \
                 patch.object(Timeshift, "stop_dump"), \
                 patch("subprocess.Popen", side_effect=fake_popen) as mock_popen:
                Timeshift._write_state({
                    "running": True,
                    "pid": 1111,
                    "adapter_id": 0,
                    "follow_pid": 2222,
                    "follow_socket": follow_sock,
                })
                path = Timeshift.retune_keep_window("FOX")
                self.assertEqual(path, live)
                cmd = mock_popen.call_args[0][0]
                self.assertIn("--dvbin-card=0", cmd)
                self.assertNotIn("--dvbin-card=1", cmd)
                data = Timeshift.load_state()
            self.assertEqual(data["adapter_id"], 0)
            self.assertEqual(data["pid"], 8888)
            self.assertEqual(data["tune_name"], "FOX")
            self.assertEqual(data["follow_pid"], 2222)
            self.assertEqual(data["socket"], sock)

    def test_retune_running_dump_does_not_spawn(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            live = os.path.join(tmp_dir, "live.ts")
            state = os.path.join(tmp_dir, "timeshift_active.json")
            sock = os.path.join(tmp_dir, "dump.sock")
            with open(live, "wb") as f:
                f.write(b"\x47" * (256 * 1024))
            with patch("engine.timeshift.TIMESHIFT_DIR", tmp_dir), \
                 patch("engine.timeshift.TIMESHIFT_FILE", live), \
                 patch("engine.timeshift.TIMESHIFT_ACTIVE_PATH", state), \
                 patch("engine.timeshift.TIMESHIFT_SOCKET_PATH", sock), \
                 patch.object(Timeshift, "_pid_alive", return_value=True), \
                 patch.object(Timeshift, "_conf_needs_full_mux", return_value=False), \
                 patch.object(Timeshift, "_wait_grew", return_value=True), \
                 patch.object(Timeshift, "_dump_command", return_value={"error": "success"}) as mock_ipc, \
                 patch("engine.timeshift.REOPEN_WATCH_SEC", 0), \
                 patch("subprocess.Popen") as mock_popen:
                Timeshift._write_state({
                    "running": True,
                    "pid": 1111,
                    "tune_name": "FOX",
                    "channel": "FOX",
                    "socket": sock,
                })
                path = Timeshift.retune_keep_window("WEWS")
                self.assertEqual(path, live)
                mock_popen.assert_not_called()
                mock_ipc.assert_called_once_with(["set_property", "dvbin-prog", "WEWS"])
                data = Timeshift.load_state()
                self.assertEqual(data["tune_name"], "WEWS")
                self.assertGreater(data["play_from"], 0)

    def test_noted_channel_still_retunes_the_running_dump(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            live = os.path.join(tmp_dir, "live.ts")
            state = os.path.join(tmp_dir, "timeshift_active.json")
            sock = os.path.join(tmp_dir, "dump.sock")
            with open(live, "wb") as f:
                f.write(b"\x47" * (256 * 1024))
            with patch("engine.timeshift.TIMESHIFT_DIR", tmp_dir), \
                 patch("engine.timeshift.TIMESHIFT_FILE", live), \
                 patch("engine.timeshift.TIMESHIFT_ACTIVE_PATH", state), \
                 patch("engine.timeshift.TIMESHIFT_SOCKET_PATH", sock), \
                 patch.object(Timeshift, "_pid_alive", return_value=True), \
                 patch.object(Timeshift, "_conf_needs_full_mux", return_value=False), \
                 patch.object(Timeshift, "_wait_grew", return_value=True), \
                 patch.object(Timeshift, "_dump_command", return_value={"error": "success"}) as mock_ipc, \
                 patch("engine.timeshift.REOPEN_WATCH_SEC", 0), \
                 patch("subprocess.Popen") as mock_popen:
                Timeshift._write_state({
                    "running": True,
                    "pid": 1111,
                    "tune_name": "FOX",
                    "channel": "FOX",
                    "socket": sock,
                })
                self.assertTrue(Timeshift.note_channel("WEWS"))
                path = Timeshift.retune_keep_window("WEWS")
                self.assertEqual(path, live)
                mock_popen.assert_not_called()
                mock_ipc.assert_called_once_with(["set_property", "dvbin-prog", "WEWS"])
                data = Timeshift.load_state()
                self.assertEqual(data["tune_name"], "WEWS")
                self.assertEqual(data.get("switching_from") or "", "")

    def test_reopen_mark_follows_the_shrunk_file(self):
        sizes = iter([5_000_000, 188])
        with patch.object(Timeshift, "_pid_alive", return_value=True), \
             patch.object(Timeshift, "dump_bytes", side_effect=lambda: next(sizes)), \
             patch.object(Timeshift, "_wait_grew", return_value=True) as grew:
            mark = Timeshift._mark_after_reopen(1, 5_000_000)
        self.assertEqual(mark, align_ts(188))
        self.assertEqual(grew.call_args.args[2], 188)

    def test_filtered_dump_will_not_retune_onto_a_zero_pid(self):
        with patch.object(Timeshift, "load_state", return_value={
            "pid": 5, "tune_name": "FOX", "channel": "FOX", "full_mux": False,
        }), \
             patch.object(Timeshift, "_pid_alive", return_value=True), \
             patch.object(Timeshift, "_conf_needs_full_mux", return_value=True), \
             patch.object(Timeshift, "_dump_command") as mock_ipc:
            self.assertFalse(Timeshift._retune_running_dump("WEWSHD"))
        mock_ipc.assert_not_called()

    def test_same_station_again_starts_a_fresh_dump(self):
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
                 patch.object(Timeshift, "_pid_alive", return_value=True), \
                 patch.object(Timeshift, "_dump_command") as mock_ipc, \
                 patch.object(Timeshift, "_wait_frontend_free"), \
                 patch.object(Timeshift, "stop_dump"), \
                 patch("subprocess.Popen", side_effect=fake_popen) as mock_popen:
                Timeshift._write_state({
                    "running": True,
                    "pid": 1111,
                    "tune_name": "FOX",
                    "channel": "FOX",
                })
                path = Timeshift.retune_keep_window("FOX")
                self.assertEqual(path, live)
                mock_ipc.assert_not_called()
                mpv_calls = [
                    c for c in mock_popen.call_args_list
                    if c.args and c.args[0] and c.args[0][0] == "mpv"
                ]
                self.assertEqual(len(mpv_calls), 1)

    def test_zero_pid_dump_does_not_lock_twice(self):
        with tempfile.TemporaryDirectory() as tmp_dir, tempfile.TemporaryDirectory() as conf_dir:
            live = os.path.join(tmp_dir, "live.ts")
            state = os.path.join(tmp_dir, "timeshift_active.json")
            sock = os.path.join(tmp_dir, "dump.sock")
            conf = os.path.join(conf_dir, "channels.conf")
            with open(conf, "w", encoding="utf-8") as f:
                f.write("WEWSHD:479028615:8VSB:0:0:3\n")
            proc = MagicMock()
            proc.pid = 4242
            proc.poll.return_value = None

            def fake_popen(*_args, **_kwargs):
                with open(live, "wb") as f:
                    f.write(b"x" * (256 * 1024))
                return proc

            class Now:
                def __init__(self, target=None, args=(), daemon=None):
                    self.target = target
                    self.args = args

                def start(self):
                    if self.target:
                        self.target(*self.args)

            with patch("engine.timeshift.TIMESHIFT_DIR", tmp_dir), \
                 patch("engine.timeshift.TIMESHIFT_FILE", live), \
                 patch("engine.timeshift.TIMESHIFT_ACTIVE_PATH", state), \
                 patch("engine.timeshift.TIMESHIFT_SOCKET_PATH", sock), \
                 patch("engine.timeshift.MPV_CHANNELS_CONF", conf), \
                 patch("engine.timeshift.threading.Thread", Now), \
                 patch.object(Timeshift, "_wait_frontend_free"), \
                 patch.object(Timeshift, "_remember_pids", return_value=True) as mock_learn, \
                 patch("subprocess.Popen", side_effect=fake_popen) as mock_popen:
                path = Timeshift.start_dump("WEWSHD")
                self.assertEqual(path, live)
                mpv_calls = [
                    c for c in mock_popen.call_args_list
                    if c.args and c.args[0] and c.args[0][0] == "mpv"
                ]
                self.assertEqual(len(mpv_calls), 1)
                self.assertIn("--dvbin-full-transponder=yes", mpv_calls[0].args[0])
                mock_learn.assert_called_once_with(live, 479028615)

    def test_retire_dump_file_unlinks_off_the_zap(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            live = os.path.join(tmp_dir, "live.ts")
            with open(live, "wb") as f:
                f.write(b"abc")
            started = []

            class HoldThread:
                def __init__(self, target=None, args=(), daemon=None):
                    self.target = target
                    self.args = args

                def start(self):
                    started.append(self.args)

            with patch("engine.timeshift.TIMESHIFT_FILE", live), \
                 patch("engine.timeshift.threading.Thread", HoldThread):
                Timeshift._retire_dump_file()
            self.assertFalse(os.path.exists(live))
            self.assertEqual(len(started), 1)
            self.assertTrue(os.path.isfile(started[0][0]))

    def test_channel_change_keeps_its_tuner(self):
        src = os.path.join(
            os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
            "engine",
            "timeshift.py",
        )
        with open(src, encoding="utf-8") as f:
            text = f.read()
        start = text.index("def retune_keep_window")
        chunk = text[start:start + 900]
        self.assertIn("cls.start_dump(name, keep_follow=True)", chunk)
        self.assertNotIn("get_available_tuner", chunk)
        self.assertNotIn("TIMESHIFT_NEXT_FILE", chunk)

    def test_snr_db_from_log_is_tenths(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log = os.path.join(tmp_dir, "dump-next.log")
            with open(log, "w", encoding="utf-8") as f:
                f.write("SNR: 100\nSNR: 223\n")
            self.assertEqual(Timeshift._snr_db_from_log(log), 22.3)

    def test_fail_tune_keeps_the_signal_and_names_the_station(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            status = os.path.join(tmp_dir, "tune_status.json")
            with patch("engine.timeshift.TUNE_STATUS_PATH", status):
                Timeshift.begin_tune("WBNX-HD", "CW 55 (WBNX)")
                Timeshift.patch_tune_status(snr_db=22.3)
                Timeshift.fail_tune("WBNX-HD", "CW 55 (WBNX)")
                data = Timeshift.load_tune_status()
            self.assertEqual(data["phase"], "failed")
            self.assertEqual(data["snr_db"], 22.3)
            self.assertEqual(data["message"], "CW 55 (WBNX) did not come up")

    def test_remember_pids_writes_the_lineup(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            conf = os.path.join(tmp_dir, "channels.conf")
            listed = os.path.join(tmp_dir, "channels.json")
            dump = os.path.join(tmp_dir, "live.ts")
            with open(conf, "w", encoding="utf-8") as f:
                f.write("WEWSHD:479028615:8VSB:0:0:3\n5.1:479028615:8VSB:0:0:3\n")
            with open(listed, "w", encoding="utf-8") as f:
                json.dump({"channels": [{"name": "WEWSHD", "service_id": 3, "video_pid": 0, "audio_pid": 0}]}, f)
            with open(dump, "wb") as f:
                f.write(b"\x47" + b"\x00" * 200)
            probe = json.dumps({
                "programs": [{
                    "program_id": 3,
                    "streams": [
                        {"codec_type": "video", "id": "0x31", "codec_name": "mpeg2video"},
                        {"codec_type": "audio", "id": "0x34", "codec_name": "ac3"},
                    ],
                }]
            })
            with patch("engine.timeshift.MPV_CHANNELS_CONF", conf), \
                 patch("engine.timeshift.CHANNELS_JSON_PATH", listed), \
                 patch("subprocess.run", return_value=MagicMock(stdout=probe)):
                self.assertTrue(Timeshift._remember_pids(dump))
                self.assertFalse(Timeshift._conf_needs_full_mux("WEWSHD"))
            with open(conf, encoding="utf-8") as f:
                text = f.read()
            self.assertIn("WEWSHD:479028615:8VSB:49:52:3", text)
            with open(listed, encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual(saved["channels"][0]["video_pid"], 49)
            self.assertEqual(saved["channels"][0]["audio_pid"], 52)

    def test_copied_video_id_needs_the_whole_tower(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            conf = os.path.join(tmp_dir, "channels.conf")
            with open(conf, "w", encoding="utf-8") as f:
                f.write(
                    "WOIO-HD:195028615:8VSB:65:68:2\n"
                    "19.1:195028615:8VSB:65:68:2\n"
                    "MeTV:195028615:8VSB:49:52:3\n"
                    "WUAB:195028615:8VSB:65:68:4\n"
                    "43.1:195028615:8VSB:65:68:4\n"
                    "FOX:183028615:8VSB:49:52:3\n"
                )
            with patch("engine.timeshift.MPV_CHANNELS_CONF", conf):
                self.assertFalse(Timeshift._conf_needs_full_mux("WOIO-HD"))
                self.assertFalse(Timeshift._conf_needs_full_mux("19.1"))
                self.assertFalse(Timeshift._conf_needs_full_mux("MeTV"))
                self.assertTrue(Timeshift._conf_needs_full_mux("WUAB"))
                self.assertTrue(Timeshift._conf_needs_full_mux("43.1"))
                self.assertFalse(Timeshift._conf_needs_full_mux("FOX"))
                self.assertEqual(Timeshift.service_id("WUAB"), 4)

    def test_shared_tune_name_uses_the_channel_number(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            conf = os.path.join(tmp_dir, "channels.conf")
            with open(conf, "w", encoding="utf-8") as f:
                f.write(
                    "KONV-LD:527028615:8VSB:0:0:1001\n"
                    "28.1:527028615:8VSB:0:0:1001\n"
                    "KONV-LD:527028615:8VSB:0:0:1002\n"
                    "28.2:527028615:8VSB:0:0:1002\n"
                    "WKYC-HD:503028615:8VSB:49:52:1\n"
                    "3.1:503028615:8VSB:49:52:1\n"
                )
            with patch("engine.timeshift.MPV_CHANNELS_CONF", conf):
                self.assertEqual(Timeshift.conf_name({
                    "tune_name": "KONV-LD", "channel_number": "28.1",
                }), "28.1")
                self.assertEqual(Timeshift.conf_name({
                    "tune_name": "KONV-LD", "channel_number": "28.2",
                }), "28.2")
                self.assertEqual(Timeshift.conf_name({
                    "tune_name": "WKYC-HD", "channel_number": "3.1",
                }), "WKYC-HD")

    def test_learned_pid_replaces_a_copy_on_that_tower_only(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            conf = os.path.join(tmp_dir, "channels.conf")
            listed = os.path.join(tmp_dir, "channels.json")
            dump = os.path.join(tmp_dir, "live.ts")
            with open(conf, "w", encoding="utf-8") as f:
                f.write(
                    "WOIO-HD:195028615:8VSB:65:68:2\n"
                    "WUAB:195028615:8VSB:65:68:4\n"
                    "43.1:195028615:8VSB:65:68:4\n"
                    "Quest:503028615:8VSB:65:68:4\n"
                )
            with open(listed, "w", encoding="utf-8") as f:
                json.dump({"channels": [
                    {"name": "WUAB", "frequency": 195028615, "service_id": 4, "video_pid": 65, "audio_pid": 68},
                    {"name": "Quest", "frequency": 503028615, "service_id": 4, "video_pid": 65, "audio_pid": 68},
                ]}, f)
            with open(dump, "wb") as f:
                f.write(b"\x47" + b"\x00" * 200)
            probe = json.dumps({
                "programs": [{
                    "program_id": 4,
                    "streams": [
                        {"codec_type": "video", "id": "0x71", "codec_name": "mpeg2video"},
                        {"codec_type": "audio", "id": "0x74", "codec_name": "ac3"},
                    ],
                }]
            })
            with patch("engine.timeshift.MPV_CHANNELS_CONF", conf), \
                 patch("engine.timeshift.CHANNELS_JSON_PATH", listed), \
                 patch("subprocess.run", return_value=MagicMock(stdout=probe)):
                self.assertTrue(Timeshift._remember_pids(dump, 195028615))
                self.assertFalse(Timeshift._conf_needs_full_mux("WUAB"))
            with open(conf, encoding="utf-8") as f:
                text = f.read()
            self.assertIn("WUAB:195028615:8VSB:113:116:4", text)
            self.assertIn("43.1:195028615:8VSB:113:116:4", text)
            self.assertIn("WOIO-HD:195028615:8VSB:65:68:2", text)
            self.assertIn("Quest:503028615:8VSB:65:68:4", text)
            with open(listed, encoding="utf-8") as f:
                saved = json.load(f)
            by_name = {row["name"]: row for row in saved["channels"]}
            self.assertEqual(by_name["WUAB"]["video_pid"], 113)
            self.assertEqual(by_name["Quest"]["video_pid"], 65)


if __name__ == "__main__":
    unittest.main()
