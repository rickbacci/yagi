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
from engine.paths import (
    GUIDE_UNIT,
    LIVE_SLICE,
    REC_SLICE,
    TUNER_SLICE,
    dump_unit,
    in_unit,
    own_scope,
    own_service,
    state_lock,
    stop_unit,
)
from engine.schedule import next_window, save_schedule

CLI_BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "yagi")


def _load_cli():
    loader = importlib.machinery.SourceFileLoader("yagi_cli", CLI_BIN)
    spec = importlib.util.spec_from_loader("yagi_cli", loader)
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
        self.assertIn("--unit=yagi-dump1.scope", cmd)
        self.assertIn(f"--slice={TUNER_SLICE}", cmd)
        self.assertEqual(cmd[cmd.index("-p") + 1], "TimeoutStopSec=2")
        self.assertEqual(cmd[cmd.index("--") + 1:], ["python3", "tower_dump.py"])

    def test_stop_unit_waits_on_systemctl(self):
        with mock.patch("engine.paths.systemd_user", return_value=True), \
                mock.patch("engine.paths.subprocess.run") as run:
            self.assertTrue(stop_unit(LIVE_SLICE))
        self.assertEqual(run.call_args[0][0], ["systemctl", "--user", "stop", LIVE_SLICE])

    def test_in_unit_reads_this_process_cgroup(self):
        group = f"0::/user.slice/yagi.slice/{LIVE_SLICE}/run-1.scope\n"
        with mock.patch("builtins.open", mock.mock_open(read_data=group)):
            self.assertTrue(in_unit(LIVE_SLICE))
            self.assertFalse(in_unit(REC_SLICE))

    def test_a_guide_grab_is_a_service_not_a_scope(self):
        with mock.patch("engine.paths.systemd_user", return_value=True):
            cmd = own_service(["python3", "yagi", "guide", "update"])
        self.assertEqual(cmd[:3], ["systemd-run", "--user", "--quiet"])
        self.assertNotIn("--scope", cmd)
        self.assertIn(f"--unit={GUIDE_UNIT}", cmd)
        self.assertIn("--service-type=exec", cmd)
        self.assertNotIn("--wait", cmd)
        self.assertNotIn("--no-block", cmd)
        self.assertEqual(cmd[cmd.index("--") + 1:], ["python3", "yagi", "guide", "update"])

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

        timer = os.path.join(os.path.dirname(CLI_BIN), "..", "systemd", "user", "yagi-record.timer")
        with open(timer, encoding="utf-8") as f:
            unit = f.read()
        slack = int(unit.split("AccuracySec=")[1].split("s")[0])
        self.assertGreaterEqual(PAD_EARLY_SEC - (60 + slack), 20)

    def test_the_timer_starts_the_update_and_returns(self):
        from engine.psip import GUIDE_STATUS_PATH

        cli = _load_cli()
        try:
            os.remove(GUIDE_STATUS_PATH)
        except OSError:
            pass
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
        self.assertNotIn("--scope", argv)
        self.assertTrue(spawn.call_args[1].get("start_new_session"))

    def test_a_failed_service_start_backs_off_instead_of_retrying_every_minute(self):
        from engine.psip import GUIDE_STATUS_PATH, read_guide_status

        cli = _load_cli()
        try:
            os.remove(GUIDE_STATUS_PATH)
        except OSError:
            pass
        failed = subprocess.CompletedProcess([], 1, "", "Failed to start transient service")
        patches = [
            mock.patch("engine.psip.clear_stale_guide_status"),
            mock.patch("engine.psip.guide_update_running", return_value=False),
            mock.patch("engine.paths.unit_active", return_value=False),
            mock.patch("engine.guide.load_guide", return_value={"updated_at": 0}),
            mock.patch("engine.guide.guide_tuner_free", return_value=True),
            mock.patch("engine.pool.free_count", return_value=2),
            mock.patch("engine.paths.systemd_user", return_value=True),
        ]
        with mock.patch.object(cli.subprocess, "run", return_value=failed) as run, \
                mock.patch.object(cli.subprocess, "Popen") as spawn:
            for patch in patches:
                patch.start()
            try:
                cli._grab_guide_if_due()
            finally:
                for patch in patches:
                    patch.stop()
        spawn.assert_not_called()
        argv = run.call_args[0][0]
        self.assertNotIn("--scope", argv)
        self.assertIn(f"--unit={GUIDE_UNIT}", argv)
        status = read_guide_status()
        self.assertGreaterEqual(int(status.get("failures") or 0), 1)
        self.assertIn("Failed to start", status.get("error") or "")
        with mock.patch.object(cli.subprocess, "run") as again, \
                mock.patch.object(cli.subprocess, "Popen") as spawn_again:
            for patch in patches:
                patch.start()
            try:
                cli._grab_guide_if_due()
            finally:
                for patch in patches:
                    patch.stop()
        again.assert_not_called()
        spawn_again.assert_not_called()

    def test_recording_finish_is_its_own_service_with_a_neutral_name(self):
        cli = _load_cli()
        ok = subprocess.CompletedProcess([], 0, "", "")
        allowed_env = {
            "HOME", "PATH", "TZ", "XDG_RUNTIME_DIR", "XDG_CONFIG_HOME",
            "XDG_CACHE_HOME", "XDG_VIDEOS_DIR",
        }
        with mock.patch("engine.paths.systemd_user", return_value=True), \
                mock.patch.object(cli.subprocess, "run", return_value=ok) as run, \
                mock.patch.object(cli.subprocess, "Popen") as spawn:
            cli._start_recording_finish()
            cli._start_recording_finish()
        spawn.assert_not_called()
        self.assertEqual(run.call_count, 2)
        units = []
        for call in run.call_args_list:
            argv = call[0][0]
            self.assertNotIn("--scope", argv)
            self.assertIn("--description=Yagi recording finish", argv)
            self.assertIn("RuntimeMaxSec=21600", argv)
            self.assertEqual(argv[-2:], ["record", "finish"])
            unit = next(part.split("=", 1)[1] for part in argv if part.startswith("--unit="))
            units.append(unit)
            self.assertNotIn(".ts", " ".join(argv))
            for i, part in enumerate(argv):
                if part != "-E":
                    continue
                key = argv[i + 1].split("=", 1)[0]
                self.assertIn(key, allowed_env)
        self.assertNotEqual(units[0], units[1])
        self.assertRegex(units[0], r"^yagi-finish-[0-9a-f]{12}\.service$")
        self.assertRegex(units[1], r"^yagi-finish-[0-9a-f]{12}\.service$")

    def test_a_failed_finish_start_is_logged_and_not_called_started(self):
        import io
        from contextlib import redirect_stdout

        cli = _load_cli()
        failed = subprocess.CompletedProcess([], 1, "", "Failed to start transient service")
        buf = io.StringIO()
        with mock.patch("engine.paths.systemd_user", return_value=True), \
                mock.patch.object(cli.subprocess, "run", return_value=failed), \
                mock.patch.object(cli.subprocess, "Popen") as spawn, \
                redirect_stdout(buf):
            cli._start_recording_finish()
        spawn.assert_not_called()
        text = buf.getvalue()
        self.assertIn("Recording finish left alone.", text)
        self.assertIn("Failed to start", text)
        self.assertNotIn("Recording finish started", text)

    def test_version_is_0_1_2(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "manifest.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["version"], "0.1.2")
        with open(os.path.join(root, "CHANGELOG.md"), encoding="utf-8") as f:
            log = f.read()
        self.assertIn("## 0.1.2", log)
        self.assertIn("## 0.1.1", log)
        self.assertIn("hover handler", log)
        self.assertIn("52 53", log)
        self.assertIn("own user service", log)

    def test_a_second_finish_steps_aside_without_dropping_the_lock(self):
        from engine.episodes import FINISH_LOCK_KEY, finish_recordings
        held, release = threading.Event(), threading.Event()

        def hold():
            with state_lock(FINISH_LOCK_KEY):
                held.set()
                release.wait(5)

        other = threading.Thread(target=hold)
        other.start()
        held.wait(5)
        try:
            with tempfile.TemporaryDirectory() as d:
                self.assertEqual(finish_recordings(d, 1000), [])
        finally:
            release.set()
            other.join()

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
                mock.patch("engine.guide.refresh_guide", return_value={"skipped": False, "attached": 1}):
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
