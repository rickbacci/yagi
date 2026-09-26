"""
Unit tests for Dual-Tuner DVR Engine.
"""

import os
import json
import time
import threading
import unittest
import tempfile
from unittest.mock import patch, MagicMock

from engine.dvr import (
    format_bytes,
    sanitize_filename,
    default_library_budget_bytes,
    resolve_library_budget_bytes,
    disk_below_floor,
    stop_reason,
    read_sidecar,
    write_sidecar,
    DvrSession,
    DvrManager,
    GIB,
    KEEP_FREE_GIB,
    GROW_BYTES,
)
from engine.tuner import TunerAdapter

# The live timer holds the real Tuner 1 lock during a Guide update.
_TUNER_LOCK = patch("engine.pool.LOCK_PREFIX", f"test-tuner-dvr-{os.getpid()}-")


def setUpModule():
    _TUNER_LOCK.start()


def tearDownModule():
    _TUNER_LOCK.stop()


class TestDvrEngine(unittest.TestCase):
    def test_format_bytes(self):
        self.assertEqual(format_bytes(512), "512 B")
        self.assertEqual(format_bytes(1024 * 50), "50.0 KB")
        self.assertEqual(format_bytes(1024 * 1024 * 128), "128.0 MB")
        self.assertEqual(format_bytes(1024 * 1024 * 1024 * 3), "3.00 GB")

    def test_sanitize_filename(self):
        raw = 'WJW: FOX 8 News / Live? *Special* "Edition" <HD>'
        sanitized = sanitize_filename(raw)
        self.assertNotIn(":", sanitized)
        self.assertNotIn("/", sanitized)
        self.assertNotIn("?", sanitized)
        self.assertNotIn("*", sanitized)
        self.assertNotIn('"', sanitized)
        self.assertNotIn("<", sanitized)
        self.assertNotIn(">", sanitized)
        self.assertTrue(sanitized.startswith("WJW_FOX_8_News"))

    def test_sanitize_filename_strips_apostrophes(self):
        sanitized = sanitize_filename("CBS Evening News with Norah O'Donnell")
        self.assertNotIn("'", sanitized)
        self.assertNotIn("’", sanitized)
        self.assertIn("Norah_ODonnell", sanitized)

    def test_dvr_session_serialization(self):
        session = DvrSession(
            session_id="dvr-test-1",
            channel_number="8.1",
            station="FOX",
            tune_name="8.1",
            program_title="Morning News",
            start_time=1700000000.0,
            duration_seconds=1800,
            adapter_id=1,
            file_path="/tmp/test.ts",
            socket_path="/tmp/sock.sock",
            pid=999999,
        )
        d = session.to_dict()
        self.assertEqual(d["session_id"], "dvr-test-1")
        self.assertEqual(d["channel_number"], "8.1")
        self.assertEqual(d["duration_seconds"], 1800)
        self.assertEqual(d["adapter_id"], 1)

        restored = DvrSession.from_dict(d)
        self.assertEqual(restored.session_id, "dvr-test-1")
        self.assertEqual(restored.station, "FOX")
        self.assertEqual(restored.duration_seconds, 1800)

    def test_active_sessions_save_and_prune(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            active_file = os.path.join(tmp_dir, "recordings_active.json")
            # Create a session with our current test runner's real PID (alive)
            live_session = DvrSession(
                session_id="live-1",
                channel_number="3.1",
                station="NBC",
                tune_name="3.1",
                program_title="News",
                start_time=time.time(),
                duration_seconds=600,
                adapter_id=0,
                file_path=os.path.join(tmp_dir, "test.ts"),
                socket_path=os.path.join(tmp_dir, "sock.sock"),
                pid=os.getpid(),
            )
            # Create a dead session with a non-existent PID
            dead_session = DvrSession(
                session_id="dead-1",
                channel_number="5.1",
                station="ABC",
                tune_name="5.1",
                program_title="Old Show",
                start_time=time.time() - 3600,
                duration_seconds=600,
                adapter_id=1,
                file_path=os.path.join(tmp_dir, "dead.ts"),
                socket_path=os.path.join(tmp_dir, "dead.sock"),
                pid=99999999,
            )

            DvrManager.save_active_sessions([live_session, dead_session], active_path=active_file)
            loaded = DvrManager.load_active_sessions(active_path=active_file)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].session_id, "live-1")

    def test_list_and_delete_recordings(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            rec_file = os.path.join(tmp_dir, "8.1-FOX_FOX_8_News_20260920_120000.ts")
            with open(rec_file, "wb") as f:
                f.write(b"MPEG-TS test content padding" * 100)

            other_file = os.path.join(tmp_dir, "notes.txt")
            with open(other_file, "w") as f:
                f.write("ignore me")

            records = DvrManager.list_recordings(recordings_dir=tmp_dir)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["channel_number"], "8.1")
            self.assertEqual(records[0]["station"], "FOX")
            self.assertEqual(records[0]["title"], "FOX 8 News")
            self.assertGreater(records[0]["size_bytes"], 0)

            # Test delete
            success = DvrManager.delete_recording(rec_file, recordings_dir=tmp_dir)
            self.assertTrue(success)
            self.assertFalse(os.path.exists(rec_file))

            with self.assertRaises(PermissionError):
                DvrManager.delete_recording("/etc/shadow", recordings_dir=tmp_dir)

    def test_refresh_library_index_writes_json(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            rec_file = os.path.join(tmp_dir, "8.1-FOX_FOX_8_News_20260920_120000.ts")
            with open(rec_file, "wb") as f:
                f.write(b"index")
            index_path = os.path.join(tmp_dir, "recordings.json")
            records = DvrManager.refresh_library_index(recordings_dir=tmp_dir, index_path=index_path)
            self.assertEqual(len(records), 1)
            with open(index_path, encoding="utf-8") as f:
                payload = json.load(f)
            self.assertEqual(len(payload["recordings"]), 1)
            self.assertEqual(payload["recordings"][0]["station"], "FOX")
            self.assertFalse(payload["recordings"][0]["playable"])
            self.assertIn("library_budget_bytes", payload)

    def test_default_library_budget_is_100_gb_on_large_disks(self):
        usage = MagicMock(total=2 * 1024**4, used=1024**4, free=1024**4)
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch("engine.dvr.shutil.disk_usage", return_value=usage):
                self.assertEqual(default_library_budget_bytes(tmp_dir), 100 * GIB)

    def test_default_library_budget_shrinks_on_tight_disks(self):
        usage = MagicMock(total=32 * GIB, used=26 * GIB, free=6 * GIB)
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch("engine.dvr.shutil.disk_usage", return_value=usage):
                self.assertEqual(default_library_budget_bytes(tmp_dir), 3 * GIB)

    def test_resolve_library_budget_off_and_fixed(self):
        self.assertIsNone(resolve_library_budget_bytes("/tmp", prefs={"library_max_gb": 0}))
        self.assertEqual(resolve_library_budget_bytes("/tmp", prefs={"library_max_gb": 20}), 20 * GIB)

    def test_enforce_library_budget_deletes_oldest(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            paths = []
            for i, name in enumerate(["old.ts", "mid.ts", "new.ts"]):
                path = os.path.join(tmp_dir, name)
                with open(path, "wb") as f:
                    f.write(b"x" * 3000)
                os.utime(path, (1000 + i, 1000 + i))
                paths.append(path)
            with patch("engine.dvr.resolve_library_budget_bytes", return_value=7000):
                removed = DvrManager.enforce_library_budget(
                    recordings_dir=tmp_dir,
                    active_path=os.path.join(tmp_dir, "active.json"),
                    rules_path=os.path.join(tmp_dir, "rules.json"),
                )
            self.assertEqual(removed, [paths[0]])
            self.assertFalse(os.path.exists(paths[0]))
            self.assertTrue(os.path.exists(paths[1]))
            self.assertTrue(os.path.exists(paths[2]))

    def _library(self, tmp_dir, rows):
        paths = {}
        for i, (name, size, side) in enumerate(rows):
            path = os.path.join(tmp_dir, name)
            with open(path, "wb") as f:
                f.write(b"x" * size)
            if side is not None:
                write_sidecar(path, side)
            os.utime(path, (1000 + i, 1000 + i))
            paths[name] = path
        return paths

    def _prune(self, tmp_dir, budget):
        with patch("engine.dvr.resolve_library_budget_bytes", return_value=budget):
            return DvrManager.enforce_library_budget(
                recordings_dir=tmp_dir,
                active_path=os.path.join(tmp_dir, "active.json"),
                rules_path=os.path.join(tmp_dir, "rules.json"),
            )

    def test_series_episodes_go_before_a_game_you_recorded(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            p = self._library(tmp_dir, [
                ("game.ts", 5000, {"status": "complete"}),
                ("mash1.ts", 2000, {"status": "complete", "rule_id": "mash"}),
                ("mash2.ts", 2000, {"status": "complete", "rule_id": "mash"}),
                ("mash3.ts", 2000, {"status": "complete", "rule_id": "mash"}),
            ])
            removed = self._prune(tmp_dir, 9000)
            self.assertEqual(removed, [p["mash1.ts"]])
            self.assertTrue(os.path.exists(p["game.ts"]))

    def test_kept_and_newest_are_never_deleted(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            p = self._library(tmp_dir, [
                ("kept.ts", 5000, {"status": "complete", "keep": True}),
                ("other.ts", 3000, {"status": "complete"}),
                ("huge_game.ts", 30000, {"status": "complete"}),
            ])
            removed = self._prune(tmp_dir, 1000)
            self.assertEqual(removed, [p["other.ts"]])
            self.assertTrue(os.path.exists(p["kept.ts"]))
            self.assertTrue(os.path.exists(p["huge_game.ts"]))

    def test_a_show_keeps_only_its_newest(self):
        from engine.rules import save_rules
        from engine.shows import show_id

        rid = show_id("mash", "19.2")
        with tempfile.TemporaryDirectory() as tmp_dir:
            save_rules([{"id": rid, "key": "mash", "channel": "19.2", "keep_last": 2}], os.path.join(tmp_dir, "rules.json"))
            p = self._library(tmp_dir, [
                (f"mash{i}.ts", 100, {"status": "complete", "rule_id": rid, "start": 100 + i}) for i in range(4)
            ] + [("kept.ts", 100, {"status": "complete", "rule_id": rid, "keep": True, "start": 1})])
            removed = self._prune(tmp_dir, None)
            self.assertEqual(sorted(removed), [p["mash0.ts"], p["mash1.ts"]])
            self.assertTrue(os.path.exists(p["kept.ts"]))

    def test_set_keep_marks_the_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            p = self._library(tmp_dir, [("show.ts", 100, {"status": "complete"})])
            self.assertTrue(DvrManager.set_keep(p["show.ts"], True, recordings_dir=tmp_dir))
            self.assertTrue(DvrManager.list_recordings(recordings_dir=tmp_dir)[0]["keep"])
            self.assertFalse(DvrManager.set_keep(os.path.join(tmp_dir, "..", "x.ts"), True, recordings_dir=tmp_dir))

    def test_enforce_library_budget_does_not_follow_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            lib = os.path.join(tmp_dir, "TV")
            outside = os.path.join(tmp_dir, "photos")
            os.makedirs(lib)
            os.makedirs(outside)
            victim = os.path.join(outside, "wedding.mp4")
            with open(victim, "wb") as f:
                f.write(b"keep" * 2000)
            trap = os.path.join(lib, "trap.ts")
            os.symlink(victim, trap)
            old = os.path.join(lib, "old.ts")
            with open(old, "wb") as f:
                f.write(b"x" * 3000)
            os.utime(old, (1000, 1000))
            new = os.path.join(lib, "new.ts")
            with open(new, "wb") as f:
                f.write(b"x" * 10)
            os.utime(new, (2000, 2000))
            names = [item["name"] for item in DvrManager.list_recordings(recordings_dir=lib)]
            self.assertEqual(names, ["new.ts", "old.ts"])
            with patch("engine.dvr.resolve_library_budget_bytes", return_value=100):
                removed = DvrManager.enforce_library_budget(
                    recordings_dir=lib,
                    active_path=os.path.join(lib, "active.json"),
                    rules_path=os.path.join(lib, "rules.json"),
                )
            self.assertEqual(removed, [old])
            self.assertFalse(os.path.exists(old))
            self.assertTrue(os.path.exists(victim))
            self.assertTrue(os.path.lexists(trap))

    @patch("subprocess.Popen")
    @patch("engine.tuner.TunerManager.adapter_is_free", return_value=True)
    def test_start_and_stop_recording_mocked(self, mock_free, mock_popen):
        fake_proc = MagicMock()
        fake_proc.pid = os.getpid()
        fake_proc.poll.return_value = None
        mock_popen.return_value = fake_proc

        with tempfile.TemporaryDirectory() as tmp_dir:
            active_file = os.path.join(tmp_dir, "recordings_active.json")
            channels_file = os.path.join(tmp_dir, "channels.json")
            with open(channels_file, "w") as f:
                json.dump([{"channel_number": "8.1", "station": "FOX", "name": "WJW-HD", "tune_name": "8.1"}], f)

            with patch.object(DvrManager, "wait_until_growing", return_value=True):
                session = DvrManager.start_recording(
                    channel_query="8.1",
                    duration=300,
                    recordings_dir=tmp_dir,
                    channels_file=channels_file,
                    active_path=active_file,
                    program_title="Monday Night Football Kickoff",
                )

            self.assertEqual(session.channel_number, "8.1")
            self.assertEqual(session.station, "FOX")
            self.assertEqual(session.adapter_id, 1)
            self.assertEqual(session.program_title, "Monday Night Football Kickoff")
            self.assertIn("Monday_Night_Football_Kickoff", session.file_path)
            rec_cmd = mock_popen.call_args_list[0][0][0]
            self.assertIn("--dvbin-card=1", rec_cmd)
            self.assertNotIn("--dvbin-card=0", rec_cmd)
            self.assertNotIn("--dvbin-full-transponder=yes", rec_cmd)
            self.assertIn("--load-scripts=no", rec_cmd)
            side = read_sidecar(session.file_path)
            self.assertEqual(side["title"], "Monday Night Football Kickoff")
            self.assertEqual(side["channel"], "8.1")
            self.assertEqual(side["status"], "recording")
            self.assertIsNone(side["end"])
            self.assertEqual(mock_popen.call_count, 1)

            # Second concurrent recording of same channel must raise RuntimeError
            with self.assertRaises(RuntimeError):
                DvrManager.start_recording(
                    channel_query="FOX",
                    duration=300,
                    recordings_dir=tmp_dir,
                    channels_file=channels_file,
                    active_path=active_file,
                )

            # Stopping the recording
            with patch.object(DvrSession, "stop", return_value=True) as mock_stop, \
                    patch.object(DvrManager, "refresh_library_index"):
                stopped = DvrManager.stop_recording("8.1", active_path=active_file)
                self.assertEqual(len(stopped), 1)
                self.assertEqual(stopped[0].channel_number, "8.1")
                mock_stop.assert_called_once()

    @patch("engine.dvr.FRONTEND_SETTLE_SECS", 0)
    @patch("subprocess.Popen")
    @patch("engine.tuner.TunerManager.adapter_is_free", return_value=False)
    def test_start_recording_refuses_busy_tuner1(self, mock_free, mock_popen):
        with tempfile.TemporaryDirectory() as tmp_dir:
            active_file = os.path.join(tmp_dir, "recordings_active.json")
            channels_file = os.path.join(tmp_dir, "channels.json")
            with open(channels_file, "w") as f:
                json.dump([{"channel_number": "8.1", "station": "FOX", "name": "WJW-HD", "tune_name": "8.1"}], f)
            with self.assertRaises(RuntimeError) as ctx:
                DvrManager.start_recording(
                    channel_query="8.1",
                    duration=300,
                    recordings_dir=tmp_dir,
                    channels_file=channels_file,
                    active_path=active_file,
                )
            self.assertIn("Both tuners are busy", str(ctx.exception))
            mock_popen.assert_not_called()

    @patch("subprocess.Popen")
    @patch("engine.tuner.TunerManager.adapter_is_free", return_value=True)
    def test_start_recording_full_mux_and_sidecar_service(self, mock_free, mock_popen):
        fake_proc = MagicMock()
        fake_proc.pid = os.getpid()
        fake_proc.poll.return_value = None
        mock_popen.return_value = fake_proc
        with tempfile.TemporaryDirectory() as tmp_dir:
            channels_file = os.path.join(tmp_dir, "channels.json")
            with open(channels_file, "w") as f:
                json.dump([{"channel_number": "43.1", "station": "GRIT", "tune_name": "GRIT"}], f)
            with patch("engine.timeshift.Timeshift._conf_needs_full_mux", return_value=True), \
                 patch("engine.timeshift.Timeshift.service_id", return_value=7), \
                 patch.object(DvrManager, "wait_until_growing", return_value=True):
                session = DvrManager.start_recording(
                    "43.1",
                    recordings_dir=tmp_dir,
                    channels_file=channels_file,
                    active_path=os.path.join(tmp_dir, "active.json"),
                )
            cmd = mock_popen.call_args_list[0][0][0]
            self.assertIn("--dvbin-full-transponder=yes", cmd)
            side = read_sidecar(session.file_path)
            self.assertTrue(side["full_mux"])
            self.assertEqual(side["service_id"], 7)
            self.assertIsNone(side["planned_end"])

    @patch("subprocess.Popen")
    @patch("engine.tuner.TunerManager.adapter_is_free", return_value=True)
    def test_start_recording_keeps_partial_when_dump_never_grows(self, mock_free, mock_popen):
        fake_proc = MagicMock()
        fake_proc.pid = os.getpid()
        fake_proc.poll.return_value = 1
        mock_popen.return_value = fake_proc
        with tempfile.TemporaryDirectory() as tmp_dir:
            channels_file = os.path.join(tmp_dir, "channels.json")
            with open(channels_file, "w") as f:
                json.dump([{"channel_number": "8.1", "station": "FOX", "tune_name": "8.1"}], f)
            active_file = os.path.join(tmp_dir, "active.json")
            with self.assertRaises(RuntimeError) as ctx:
                DvrManager.start_recording(
                    "8.1",
                    recordings_dir=tmp_dir,
                    channels_file=channels_file,
                    active_path=active_file,
                )
            self.assertIn("partial file", str(ctx.exception))
            ts_files = [name for name in os.listdir(tmp_dir) if name.endswith(".ts")]
            self.assertEqual(len(ts_files), 1)
            side = read_sidecar(os.path.join(tmp_dir, ts_files[0]))
            self.assertEqual(side["status"], "failed")
            self.assertEqual(DvrManager.load_active_sessions(active_file), [])
            fake_proc.kill.assert_not_called()

    def test_list_prefers_sidecar_over_filename(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            rec_file = os.path.join(tmp_dir, "8.1-FOX_Wrong_Title_20260920_120000.ts")
            with open(rec_file, "wb") as f:
                f.write(b"x" * (256 * 1024))
            from engine.dvr import write_sidecar
            write_sidecar(rec_file, {
                "title": "MASH",
                "station": "METV",
                "channel": "19.2",
                "service_id": 4,
                "full_mux": True,
                "status": "complete",
                "start": 10,
                "end": 20,
            })
            records = DvrManager.list_recordings(recordings_dir=tmp_dir)
            self.assertEqual(records[0]["title"], "MASH")
            self.assertEqual(records[0]["station"], "METV")
            self.assertEqual(records[0]["channel_number"], "19.2")
            self.assertEqual(records[0]["service_id"], 4)
            self.assertTrue(records[0]["playable"])
            DvrManager.delete_recording(rec_file, recordings_dir=tmp_dir)
            self.assertFalse(os.path.exists(rec_file))
            self.assertFalse(os.path.exists(os.path.splitext(rec_file)[0] + ".json"))

    def test_disk_floor_and_end_time(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch("engine.dvr.shutil.disk_usage") as mock_usage:
                mock_usage.return_value = MagicMock(free=(KEEP_FREE_GIB * GIB) - 1)
                self.assertTrue(disk_below_floor(tmp_dir))
                mock_usage.return_value = MagicMock(free=(KEEP_FREE_GIB * GIB) + 1)
                self.assertFalse(disk_below_floor(tmp_dir))
        self.assertEqual(stop_reason(tmp_dir, now=100, end_unix=100), "end")
        with patch("engine.dvr.disk_below_floor", return_value=True):
            self.assertEqual(stop_reason(tmp_dir, now=1, end_unix=None), "disk")
        with patch("engine.dvr.disk_below_floor", return_value=False):
            self.assertIsNone(stop_reason(tmp_dir, now=1, end_unix=None))

    def test_wait_until_growing_accepts_a_live_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "live.ts")
            with open(path, "wb") as f:
                f.write(b"")
            proc = MagicMock()
            proc.poll.return_value = None

            def grow():
                time.sleep(0.05)
                with open(path, "wb") as f:
                    f.write(b"x" * GROW_BYTES)

            threading.Thread(target=grow).start()
            self.assertTrue(DvrManager.wait_until_growing(proc, path, timeout=1.0))

    def test_tiny_failed_file_stays_unplayable(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            rec_file = os.path.join(tmp_dir, "stub.ts")
            with open(rec_file, "wb") as f:
                f.write(b"x" * 100)
            from engine.dvr import write_sidecar
            write_sidecar(rec_file, {"title": "Gone", "status": "failed", "channel": "8.1"})
            records = DvrManager.list_recordings(recordings_dir=tmp_dir)
            self.assertEqual(records[0]["status"], "failed")
            self.assertFalse(records[0]["playable"])
            self.assertTrue(os.path.exists(rec_file))

    def test_sweep_stops_a_recording_past_its_end(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            active = os.path.join(tmp_dir, "active.json")
            rec = os.path.join(tmp_dir, "show.ts")
            with open(rec, "wb") as f:
                f.write(b"x" * 1024)
            session = DvrSession(
                session_id="s1",
                channel_number="8.1",
                station="FOX",
                tune_name="WJW-HD",
                program_title="Game",
                start_time=time.time() - 500,
                duration_seconds=60,
                adapter_id=1,
                file_path=rec,
                socket_path="",
                pid=os.getpid(),
            )
            DvrManager.save_active_sessions([session], active)
            with patch.object(DvrManager, "stop_recording", return_value=[session]) as stop:
                stopped = DvrManager.sweep_active(active_path=active)
            self.assertEqual(len(stopped), 1)
            stop.assert_called_once_with("s1", active_path=active)

    def test_sweep_leaves_a_recording_that_is_still_inside_its_window(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            active = os.path.join(tmp_dir, "active.json")
            rec = os.path.join(tmp_dir, "show.ts")
            with open(rec, "wb") as f:
                f.write(b"x" * 1024)
            session = DvrSession(
                session_id="s2",
                channel_number="8.1",
                station="FOX",
                tune_name="WJW-HD",
                program_title="Game",
                start_time=time.time(),
                duration_seconds=3600,
                adapter_id=1,
                file_path=rec,
                socket_path="",
                pid=os.getpid(),
            )
            DvrManager.save_active_sessions([session], active)
            with patch("engine.dvr.disk_below_floor", return_value=False), patch.object(
                DvrManager, "stop_recording"
            ) as stop:
                stopped = DvrManager.sweep_active(active_path=active)
            self.assertEqual(stopped, [])
            stop.assert_not_called()

    def test_keep_copies_the_pause_and_leaves_the_dump(self):
        from engine.dvr import MIN_PLAYABLE_BYTES, read_sidecar
        with tempfile.TemporaryDirectory() as tmp_dir:
            dump = os.path.join(tmp_dir, "live.ts")
            library = os.path.join(tmp_dir, "lib")
            payload = b"a" * (MIN_PLAYABLE_BYTES + 4096)
            with open(dump, "wb") as handle:
                handle.write(payload)
            state = {
                "running": True,
                "tune_name": "WEWSHD",
                "channel": "WEWSHD",
                "playhead_byte": 4096,
                "full_mux": True,
                "service_id": 4,
                "path": dump,
            }
            dest = DvrManager.keep_pause(recordings_dir=library, state=state, dump_path=dump)
            self.assertEqual(os.path.getsize(dump), len(payload))
            self.assertEqual(os.path.getsize(dest), len(payload) - 4096)
            side = read_sidecar(dest)
            self.assertEqual(side["kept_from"], "pause")
            self.assertEqual(side["service_id"], 4)
            self.assertTrue(side["full_mux"])
            with self.assertRaises(RuntimeError):
                DvrManager.keep_pause("WJW-HD", recordings_dir=library, state=state, dump_path=dump)
            short = dict(state)
            short["playhead_byte"] = len(payload) - 100
            with self.assertRaises(RuntimeError):
                DvrManager.keep_pause(recordings_dir=library, state=short, dump_path=dump)


if __name__ == "__main__":
    unittest.main()
