"""Hidden stations stay off Watchable, and 19.1 can hide without 19.10."""

import os
import tempfile
import unittest

from engine.hidden import hide_channel, is_hidden_channel, load_hidden, show_channel
from player.controller import surfable_channels


class TestHidden(unittest.TestCase):
    def test_missing_file_is_empty_and_unwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "hidden.json")
            self.assertEqual(load_hidden(path), [])
            self.assertFalse(os.path.exists(path))

    def test_show_and_hide_one_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "hidden.json")
            hide_channel("19.1", path)
            self.assertEqual(load_hidden(path), ["19.1"])
            show_channel("19.1", path)
            self.assertEqual(load_hidden(path), [])
            hide_channel("19.1", path)
            self.assertIn("19.1", load_hidden(path))

    def test_an_empty_file_stays_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "hidden.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("[]")
            self.assertEqual(load_hidden(path), [])

    def test_surf_skips_a_hidden_number_and_keeps_the_other_copy(self):
        channels = [
            {"channel_number": "19.1", "tune_name": "WOIO-HD", "name": "WOIO-HD"},
            {"channel_number": "19.10", "tune_name": "WOIO-HD", "name": "WOIO-HD", "is_translator": True},
            {"channel_number": "5.6", "tune_name": "QVC", "name": "QVC"},
            {"channel_number": "23.5", "tune_name": "QVC", "name": "QVC"},
        ]
        pool = surfable_channels(channels, channel_filter="watchable", hidden=["19.1", "23.5"])
        self.assertEqual([ch["channel_number"] for ch in pool], ["19.10", "5.6"])


if __name__ == "__main__":
    unittest.main()
