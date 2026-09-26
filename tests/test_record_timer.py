"""The record timer: recorders outlive it, and a Guide update never makes a recording wait."""

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock

from engine.dvr import DvrManager, read_sidecar, write_sidecar
from engine.guide import GUIDE_GRAB_GAP_SEC, guide_grab_due, run_guide_update
from engine.paths import LIVE_SLICE, REC_SLICE, TUNER_SLICE, dump_unit, in_unit, own_scope, state_lock, stop_unit
from engine.schedule import next_window, save_schedule

CLI_BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "omarchy-tv")


def _load_cli():
    loader = importlib.machinery.SourceFileLoader("omarchy_tv_cli", CLI_BIN)
    spec = importlib.util.spec_from_loader("omarchy_tv_cli", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class TestOwnScope(unittest.TestCase):
    def test_wraps_in_a_user_scope_when_systemd_is_there(self):
        with tempfile.TemporaryDirectory() as run:
            os.makedirs(os.path.join(run, "systemd"))
            open(os.path.join(run, "systemd", "private"), "w").close()
            with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": run}), \
                    mock.patch("engine.paths.shutil.which", return_value="/usr/bin/systemd-run"):
                cmd = own_scope(["mpv", "dvb://MeTV"])
        self.assertEqual(cmd[:3], ["systemd-run", "--user", "--scope"])
        self.assertEqual(cmd[-2:], ["mpv", "dvb://MeTV"])

    def test_plain_without_a_user_manager(self):
        with tempfile.TemporaryDirectory() as run:
            with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": run}):
                self.assertEqual(own_scope(["mpv"]), ["mpv"])
                self.assertFalse(stop_unit(dump_unit(0)))

    def test_a_named_unit_in_a_slice_stops_within_two_seconds(self):
        with mock.patch("engine.paths.systemd_user", return_value=True):
            cmd = own_scope(["python3", "tower_dump.py"], unit=dump_unit(1), slice_name=TUNER_SLICE)
        self.assertIn("--unit=omarchy-tv-dump1.scope", cmd)
        self.assertIn(f"--slice={TUNER_SLICE}", cmd)
        self.assertEqual(cmd[cmd.index("-p") + 1], "TimeoutStopSec=2")
        self.assertEqual(cmd[cmd.index("--") + 1:], ["python3", "tower_dump.py"])

    def test_stop_unit_waits_on_systemctl(self):
        with mock.patch("engine.paths.systemd_user", return_value=True), \
                mock.patch("engine.paths.subprocess.run") as run:
            self.assertTrue(stop_unit(LIVE_SLICE))
        self.assertEqual(run.call_args[0][0], ["systemctl", "--user", "stop", LIVE_SLICE])

    def test_in_unit_reads_this_process_cgroup(self):
        group = f"0::/user.slice/omarchy-tv.slice/{LIVE_SLICE}/run-1.scope\n"
        with mock.patch("builtins.open", mock.mock_open(read_data=group)):
            self.assertTrue(in_unit(LIVE_SLICE))
            self.assertFalse(in_unit(REC_SLICE))

    def test_the_process_leaves_the_callers_cgroup(self):
        cmd = own_scope(["sleep", "2"])
        if cmd[0] != "systemd-run":
            self.skipTest("no systemd user manager")
        proc = subprocess.Popen(cmd, start_new_session=True)
        try:
            for _ in range(50):
                try:
                    with open(f"/proc/{proc.pid}/cgroup", encoding="utf-8") as f:
                        group = f.read()
                    with open(f"/proc/{proc.pid}/cmdline", encoding="utf-8") as f:
                        line = f.read()
                except OSError:
                    group, line = "", ""
                if os.path.basename(line.split("\0")[0]) == "sleep":
                    break
                proc.poll()
                time.sleep(0.05)
            with open("/proc/self/cgroup", encoding="utf-8") as f:
                mine = f.read()
            self.assertEqual(os.path.basename(line.split("\0")[0]), "sleep")
            self.assertIn(".scope", group)
            self.assertNotEqual(group, mine)
        finally:
            proc.kill()
            proc.wait()


class TestGuideStepsAside(unittest.TestCase):
    def test_no_guide_update_inside_ten_minutes_of_a_recording(self):
        now = 1_000_000.0
        stale = now - GUIDE_GRAB_GAP_SEC - 1
        self.assertTrue(guide_grab_due(now, stale, False))
        self.assertFalse(guide_grab_due(now, stale, False, next_record_at=now + 300))
        self.assertTrue(guide_grab_due(now, stale, False, next_record_at=now + 3600))

    def test_next_window_skips_missed_and_ended_rows(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "schedule.json")
            save_schedule([
                {"id": "a", "start_unix": 5000, "duration_sec": 1800, "status": "missed"},
                {"id": "b", "start_unix": 100, "duration_sec": 60},
                {"id": "c", "start_unix": 9000, "duration_sec": 1800, "pad_early_sec": 60},
            ], path)
            self.assertEqual(next_window(now=4000, path=path), 8940)
            self.assertIsNone(next_window(now=20000, path=path))

    def test_a_show_arms_before_the_next_tick_can_miss_its_start(self):
        from engine.schedule import PAD_EARLY_SEC

        timer = os.path.join(os.path.dirname(CLI_BIN), "..", "systemd", "user", "omarchy-tv-record.timer")
        with open(timer, encoding="utf-8") as f:
            unit = f.read()
        slack = int(unit.split("AccuracySec=")[1].split("s")[0])
        self.assertGreaterEqual(PAD_EARLY_SEC - (60 + slack), 20)

    def test_the_timer_starts_the_update_and_returns(self):
        cli = _load_cli()
        with mock.patch("engine.psip.clear_stale_guide_status"), \
                mock.patch("engine.psip.guide_update_running", return_value=False), \
                mock.patch("engine.guide.load_guide", return_value={"updated_at": 0}), \
                mock.patch("engine.guide.guide_tuner_free", return_value=True), \
                mock.patch("engine.pool.free_count", return_value=2), \
                mock.patch("engine.guide.refresh_guide") as inline, \
                mock.patch.object(cli.subprocess, "Popen") as spawn:
            cli._grab_guide_if_due()
        inline.assert_not_called()
        argv = spawn.call_args[0][0]
        self.assertEqual(argv[-2:], ["guide", "update"])
        self.assertTrue(spawn.call_args[1].get("start_new_session"))

    def test_a_second_update_steps_aside(self):
        key = f"test-guide-update-{os.getpid()}"
        held, release = threading.Event(), threading.Event()

        def hold():
            with state_lock(key):
                held.set()
                release.wait(5)

        other = threading.Thread(target=hold)
        other.start()
        held.wait(5)
        try:
            with mock.patch("engine.guide.GUIDE_UPDATE_LOCK_KEY", key), \
                    mock.patch("engine.guide.refresh_guide") as refresh:
                self.assertEqual(run_guide_update(grabber=dict), "running")
            refresh.assert_not_called()
        finally:
            release.set()
            other.join()
        with mock.patch("engine.guide.GUIDE_UPDATE_LOCK_KEY", key), \
                mock.patch("engine.guide.refresh_guide", return_value={"skipped": False}):
            self.assertEqual(run_guide_update(grabber=dict), "done")


class TestDeadRecorder(unittest.TestCase):
    def test_a_recorder_that_died_is_no_longer_recording(self):
        with tempfile.TemporaryDirectory() as d:
            small = os.path.join(d, "small.ts")
            big = os.path.join(d, "big.ts")
            with open(small, "wb") as f:
                f.write(b"\x47" * 40_000)
            with open(big, "wb") as f:
                f.write(b"\x47" * 400_000)
            active = os.path.join(d, "active.json")
            rows = []
            for i, path in enumerate((small, big)):
                write_sidecar(path, {"status": "recording", "start": 1, "end": None})
                rows.append({"session_id": f"s{i}", "file_path": path, "pid": 999_999_9,
                             "socket_path": os.path.join(d, f"{i}.sock"), "start_time": 1})
            with open(active, "w", encoding="utf-8") as f:
                json.dump(rows, f)
            self.assertEqual(DvrManager.load_active_sessions(active), [])
            self.assertEqual(read_sidecar(small)["status"], "failed")
            self.assertEqual(read_sidecar(big)["status"], "complete")
            self.assertEqual(read_sidecar(big)["stopped_reason"], "exited")


if __name__ == "__main__":
    unittest.main()
