"""
Unit tests for Omarchy TV - Electronic Program Guide (EPG)
"""

import os
import unittest
import tempfile
from engine.guide import load_guide, save_default_guide, get_channel_program


class TestGuide(unittest.TestCase):
    def test_default_guide_generation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            guide_file = os.path.join(tmp_dir, "guide.json")
            data = save_default_guide(guide_path=guide_file)
            self.assertTrue(os.path.exists(guide_file))
            self.assertIn("channels", data)
            self.assertIn("3.1", data["channels"])
            self.assertEqual(data["channels"]["3.1"]["network"], "NBC")
            self.assertIn("title", data["channels"]["3.1"])

    def test_get_channel_program(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            guide_file = os.path.join(tmp_dir, "guide.json")
            data = load_guide(guide_path=guide_file)

            # Match by channel number
            nbc_prog = get_channel_program("3.1", guide_data=data)
            self.assertIsNotNone(nbc_prog)
            self.assertEqual(nbc_prog["network"], "NBC")

            # Match by station callsign
            fox_prog = get_channel_program("FOX", guide_data=data)
            self.assertIsNotNone(fox_prog)
            self.assertEqual(fox_prog["network"], "FOX")

            # Match by network
            abc_prog = get_channel_program("ABC", guide_data=data)
            self.assertIsNotNone(abc_prog)
            self.assertEqual(abc_prog["network"], "ABC")


    def test_get_timeline_grid(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            guide_file = os.path.join(tmp_dir, "guide.json")
            save_default_guide(guide_path=guide_file)
            from engine.guide import get_timeline_grid
            grid = get_timeline_grid(guide_data=load_guide(guide_path=guide_file))
            self.assertIn("slots", grid)
            self.assertIn("rows", grid)
            self.assertGreater(len(grid["rows"]), 0)
            self.assertEqual(grid["rows"][0]["channel_number"], "3.1")

    def test_get_slot_program_now_and_next(self):
        from engine.guide import get_slot_program, BROADCAST_SCHEDULES

        nbc = BROADCAST_SCHEDULES["3.1"]
        now = get_slot_program(nbc, 0)
        self.assertEqual(now["label"], "Now Playing")
        self.assertEqual(now["title"], nbc["title"])
        self.assertIn("6:30 PM", now["time_label"])
        self.assertIn("7:00 PM", now["time_label"])

        nxt = get_slot_program(nbc, 1)
        self.assertEqual(nxt["label"], "Up Next")
        self.assertEqual(nxt["title"], nbc["next_title"])
        self.assertEqual(nxt["time_label"], "From 7:00 PM")

        empty_next = get_slot_program({"title": "Live"}, 1)
        self.assertEqual(empty_next["title"], "Upcoming")
        self.assertEqual(empty_next["time_label"], "Next")

    def test_match_guide_program_from_raw_scan(self):
        from engine.guide import match_guide_program, BROADCAST_SCHEDULES

        fox = match_guide_program({"name": "FOX", "raw_name": "FOX"}, BROADCAST_SCHEDULES)
        self.assertIsNotNone(fox)
        self.assertEqual(fox["network"], "FOX")

        nbc = match_guide_program({"name": "WKYC-HD", "raw_name": "WKYC-HD"}, BROADCAST_SCHEDULES)
        self.assertEqual(nbc["title"], BROADCAST_SCHEDULES["3.1"]["title"])

        uni = match_guide_program({"name": "WQHS-DT", "tune_name": "WQHS-DT"}, BROADCAST_SCHEDULES)
        self.assertEqual(uni["network"], "Univision")

        numbered = match_guide_program({"name": "FOX", "channel_number": "5.1"}, BROADCAST_SCHEDULES)
        self.assertEqual(numbered["network"], "ABC")


if __name__ == "__main__":
    unittest.main()
