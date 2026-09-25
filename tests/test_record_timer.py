"""The record timer: recorders outlive it, and a Guide update never makes a recording wait."""

import json
import os
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from engine.dvr import DvrManager, read_sidecar, write_sidecar
from engine.guide import GUIDE_GRAB_GAP_SEC, guide_grab_due
from engine.paths import own_scope
from engine.schedule import next_window, save_schedule


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
