"""Timeshift pause-live buffer."""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from engine.timeshift import Timeshift


class TestTimeshift(unittest.TestCase):
    def test_is_active_false_without_session(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "timeshift_active.json")
            self.assertFalse(Timeshift.is_active(active_path=path))

    def test_start_reuses_existing_session(self):
        existing = MagicMock()
        with patch.object(Timeshift, "active_session", return_value=existing):
            self.assertIs(Timeshift.start("8.1"), existing)

    @patch("engine.timeshift.DvrManager.start_recording")
    @patch.object(Timeshift, "stop")
    @patch.object(Timeshift, "active_session", return_value=None)
    def test_start_records_into_timeshift_dir(self, _active, _stop, mock_start):
        mock_start.return_value = MagicMock()
        Timeshift.start("WKYC-HD")
        kwargs = mock_start.call_args.kwargs
        self.assertEqual(kwargs["duration"], 15 * 60)
        self.assertTrue(kwargs["recordings_dir"].endswith("timeshift"))
        self.assertTrue(kwargs["active_path"].endswith("timeshift_active.json"))

    def test_buffer_path_returns_newest_dump(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            older = os.path.join(tmp_dir, "old.ts")
            newer = os.path.join(tmp_dir, "new.ts")
            with open(older, "wb") as f:
                f.write(b"a")
            os.utime(older, (1, 1))
            with open(newer, "wb") as f:
                f.write(b"b")
            os.utime(newer, (100, 100))
            with patch("engine.timeshift.TIMESHIFT_DIR", tmp_dir):
                with patch.object(Timeshift, "active_session", return_value=None):
                    self.assertEqual(Timeshift.buffer_path(), newer)


if __name__ == "__main__":
    unittest.main()
