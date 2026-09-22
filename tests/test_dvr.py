"""
Unit tests for Dual-Tuner DVR Engine.
"""

import os
import json
import time
import unittest
import tempfile
from unittest.mock import patch, MagicMock

from engine.dvr import (
    format_bytes,
    sanitize_filename,
    default_library_budget_bytes,
    resolve_library_budget_bytes,
    DvrSession,
    DvrManager,
    GIB,
)
from engine.tuner import TunerAdapter


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

    def test_default_library_budget_is_small_on_large_disks(self):
        usage = MagicMock(total=2 * 1024**4, used=1024**4, free=1024**4)
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch("engine.dvr.shutil.disk_usage", return_value=usage):
                self.assertEqual(default_library_budget_bytes(tmp_dir), 20 * GIB)

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
                )
            self.assertEqual(removed, [os.path.realpath(paths[0])])
            self.assertFalse(os.path.exists(paths[0]))
            self.assertTrue(os.path.exists(paths[1]))
            self.assertTrue(os.path.exists(paths[2]))

    @patch("subprocess.Popen")
    @patch("engine.tuner.TunerManager.get_available_tuner")
    def test_start_and_stop_recording_mocked(self, mock_get_tuner, mock_popen):
        fake_tuner = MagicMock()
        fake_tuner.adapter_id = 1
        fake_tuner.supports_atsc = True
        fake_tuner.is_busy = False
        mock_get_tuner.return_value = fake_tuner

        fake_proc = MagicMock()
        fake_proc.pid = os.getpid()
        fake_proc.poll.return_value = None
        mock_popen.return_value = fake_proc

        with tempfile.TemporaryDirectory() as tmp_dir:
            active_file = os.path.join(tmp_dir, "recordings_active.json")
            channels_file = os.path.join(tmp_dir, "channels.json")
            with open(channels_file, "w") as f:
                json.dump([{"channel_number": "8.1", "station": "FOX", "name": "WJW-HD", "tune_name": "8.1"}], f)

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
            with patch.object(DvrSession, "stop", return_value=True) as mock_stop:
                stopped = DvrManager.stop_recording("8.1", active_path=active_file)
                self.assertEqual(len(stopped), 1)
                self.assertEqual(stopped[0].channel_number, "8.1")
                mock_stop.assert_called_once()


if __name__ == "__main__":
    unittest.main()
