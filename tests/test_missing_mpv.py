"""A missing mpv is a failed open, not a traceback."""

import os
import tempfile
import unittest
from unittest.mock import patch


class TestMissingMpv(unittest.TestCase):
    def test_launch_returns_false_when_mpv_is_missing(self):
        from engine.timeshift import Timeshift
        from player.controller import MpvController

        with tempfile.TemporaryDirectory() as folder:
            recording = os.path.join(folder, "show.ts")
            with open(recording, "wb") as handle:
                handle.write(b"x" * 4096)
            player = MpvController(socket_path=os.path.join(folder, "sock"))
            with patch("player.controller.subprocess.Popen", side_effect=FileNotFoundError("mpv")):
                ok = player.launch_file(recording, mode="recording", channel="8.1", station="FOX")
            self.assertFalse(ok)
            self.assertIsNone(player.proc)
            status = Timeshift.load_tune_status()
            self.assertEqual(status.get("message"), "mpv is not installed.")
