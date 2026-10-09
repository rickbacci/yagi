"""Shared state is changed by one process at a time."""

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest

from engine.dvr import DvrManager, sidecar_path
from engine.paths import state_lock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _child(code: str, env=None) -> subprocess.Popen:
    full_env = dict(os.environ)
    full_env.update(env or {})
    full_env["PYTHONPATH"] = REPO
    return subprocess.Popen([sys.executable, "-c", code], env=full_env)


class TestStateLock(unittest.TestCase):
    def test_another_process_holds_it_until_it_lets_go(self):
        with tempfile.TemporaryDirectory() as tmp:
            key = os.path.join(tmp, "state.json")
            ready = os.path.join(tmp, "ready")
            child = _child(
                "import time\n"
                "from engine.paths import state_lock\n"
                f"with state_lock({key!r}):\n"
                f"    open({ready!r}, 'w').close()\n"
                "    time.sleep(0.6)\n"
            )
            try:
                deadline = time.time() + 5
                while not os.path.exists(ready) and time.time() < deadline:
                    time.sleep(0.02)
                with self.assertRaises(TimeoutError):
                    with state_lock(key, timeout=0.1):
                        pass
                with state_lock(key, timeout=5):
                    pass
            finally:
                child.wait(timeout=5)

    def test_nests_inside_one_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            key = os.path.join(tmp, "state.json")
            with state_lock(key):
                with state_lock(key, timeout=0.1):
                    pass
            with state_lock(key, timeout=0.1):
                pass

    def test_two_processes_patching_timeshift_state_lose_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"XDG_CONFIG_HOME": tmp}
            code = (
                "import sys\n"
                "from engine.timeshift import Timeshift\n"
                "key = sys.argv[1]\n"
                "for n in range(60):\n"
                "    Timeshift.patch_state(**{key + str(n): n})\n"
            )
            kids = []
            for key in ("a", "b"):
                full_env = dict(os.environ, PYTHONPATH=REPO, **env)
                kids.append(subprocess.Popen([sys.executable, "-c", code, key], env=full_env))
            for kid in kids:
                self.assertEqual(kid.wait(timeout=30), 0)
            with open(os.path.join(tmp, "yagi", "timeshift_active.json"), encoding="utf-8") as f:
                state = json.load(f)
            for key in ("a", "b"):
                for n in range(60):
                    self.assertEqual(state.get(f"{key}{n}"), n)


class TestPruneLeavesAWritingFile(unittest.TestCase):
    def test_budget_prune_skips_a_fresh_file_and_drops_old_sidecars(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.path.join(tmp, "3.1-WKYC_Old_20260901_200000.ts")
            fresh = os.path.join(tmp, "3.1-WKYC_Now_20260923_200000.ts")
            for path in (old, fresh):
                with open(path, "wb") as f:
                    f.write(b"x" * 4096)
                with open(sidecar_path(path), "w", encoding="utf-8") as f:
                    json.dump({"status": "complete"}, f)
            long_ago = time.time() - 3600
            os.utime(old, (long_ago, long_ago))
            os.utime(fresh, (long_ago + 60, long_ago + 60))
            os.utime(fresh, None)
            from unittest.mock import patch
            with patch("engine.dvr.resolve_library_budget_bytes", return_value=1):
                removed = DvrManager.enforce_library_budget(
                    recordings_dir=tmp,
                    active_path=os.path.join(tmp, "active.json"),
                )
            self.assertEqual(removed, [old])
            self.assertFalse(os.path.exists(sidecar_path(old)))
            self.assertTrue(os.path.exists(fresh))


if __name__ == "__main__":
    unittest.main()


class TestTunerLock(unittest.TestCase):
    """Live TV and scans claim a tuner under the same lock recordings and the Guide use."""

    def _hold(self, key):
        import threading

        held, done = threading.Event(), threading.Event()

        def run():
            with state_lock(key):
                held.set()
                done.wait(5)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        held.wait(2)
        return done, thread

    def _start_live(self, claims):
        from unittest import mock
        from engine import pool
        from engine.timeshift import Timeshift

        with mock.patch.object(Timeshift, "load_state", return_value={}), \
                mock.patch("engine.pool.claims", return_value=claims), \
                mock.patch.object(Timeshift, "wipe"), \
                mock.patch.object(Timeshift, "_reap_orphan_dumps"), \
                mock.patch("engine.timeshift.LIVE_LOCK_WAIT_SECS", 0.2), \
                mock.patch.object(Timeshift, "_capture_live") as capture:
            with self.assertRaises(pool.BothTunersBusy):
                Timeshift.start_dump("LAFF", adapter_id=0)
        capture.assert_not_called()

    def test_live_gives_way_to_a_recording_mid_start(self):
        from engine import pool

        done, thread = self._hold(pool.lock_key(0))
        try:
            self._start_live({})
        finally:
            done.set()
            thread.join(2)

    def test_live_refuses_a_tuner_a_recording_took_while_it_waited(self):
        self._start_live({0: "record"})

    def test_a_scan_reports_busy_while_the_tuner_is_locked(self):
        from unittest import mock
        from engine import pool
        from engine.scanner import AtscScanner

        done, thread = self._hold(pool.lock_key(1))
        try:
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch("engine.scanner.SCAN_STATUS_PATH", os.path.join(tmp, "scan.json")), \
                    mock.patch("engine.scanner.TunerManager.adapter_is_free", return_value=True), \
                    mock.patch("engine.pool.claims", return_value={}):
                events = list(AtscScanner(adapter_id=1).scan())
        finally:
            done.set()
            thread.join(2)
        self.assertEqual(events[0]["status"], "error")
