"""
Unit tests for Omarchy TV - Electronic Program Guide (EPG)
"""

import os
import json
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

    def test_default_guide_has_evening_programs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            guide_file = os.path.join(tmp_dir, "guide.json")
            data = save_default_guide(guide_path=guide_file)
            nbc = data["channels"]["3.1"]["programs"]
            self.assertGreaterEqual(len(nbc), 6)
            self.assertEqual(nbc[0]["start"], "6:00 PM")
            fox = data["channels"]["8.1"]["programs"]
            self.assertTrue(any(p.get("title") for p in fox))

    def test_load_guide_writes_programs_onto_now_next_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            guide_file = os.path.join(tmp_dir, "guide.json")
            with open(guide_file, "w", encoding="utf-8") as f:
                json.dump({
                    "updated_at": 1,
                    "channels": {
                        "8.1": {
                            "network": "FOX",
                            "station": "FOX",
                            "title": "FOX 8 News at 6:00 PM",
                            "start_time": "6:00 PM",
                            "end_time": "7:00 PM",
                        }
                    },
                }, f)
            data = load_guide(guide_path=guide_file)
            self.assertGreaterEqual(len(data["channels"]["8.1"]["programs"]), 6)
            with open(guide_file, encoding="utf-8") as f:
                on_disk = json.load(f)
            self.assertGreaterEqual(len(on_disk["channels"]["8.1"]["programs"]), 6)
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

    def test_merge_lineup_uses_scanned_channels_not_just_templates(self):
        from engine.guide import merge_lineup

        channels = [
            {
                "channel_number": "8.1",
                "network": "FOX",
                "callsign": "WJW",
                "tune_name": "8.1 WJW",
                "display_name": "FOX 8 (WJW)",
            },
            {
                "channel_number": "53.2",
                "network": "Daystar",
                "callsign": "WCDN-2",
                "tune_name": "53.2 WCDN",
                "name": "Daystar Español",
            },
        ]
        merged = merge_lineup(channels, {})
        self.assertIn("8.1", merged)
        self.assertIn("53.2", merged)
        self.assertEqual(merged["8.1"]["tune_name"], "8.1 WJW")
        self.assertEqual(merged["8.1"]["station"], "WJW")
        self.assertGreaterEqual(len(merged["8.1"]["programs"]), 6)
        self.assertEqual(merged["53.2"]["callsign"], "WCDN-2")
        self.assertEqual(merged["53.2"]["programs"], [])

    def test_merge_lineup_keeps_live_programs(self):
        from engine.guide import merge_lineup

        existing = {
            "8.1": {
                "programs": [{"start": "7:00 PM", "end": "8:00 PM", "title": "Live game"}],
                "title": "Live game",
                "source": "psip",
            }
        }
        merged = merge_lineup(
            [{"channel_number": "8.1", "network": "FOX", "callsign": "WJW", "tune_name": "FOX"}],
            existing,
        )
        self.assertEqual(merged["8.1"]["programs"][0]["title"], "Live game")

    def test_now_and_next_covers_wall_clock(self):
        from engine.guide import now_and_next

        programs = [
            {"start": "6:00 PM", "end": "7:00 PM", "title": "News"},
            {"start": "7:00 PM", "end": "8:00 PM", "title": "Game"},
        ]
        now, nxt = now_and_next(programs, now_minutes=18 * 60 + 30)
        self.assertEqual(now["title"], "News")
        self.assertEqual(nxt["title"], "Game")
        evening = now_and_next(programs, now_minutes=10 * 60)
        self.assertIsNone(evening[0])

    def test_refresh_skips_grabber_when_recording_holds_tuner1(self):
        from engine.guide import refresh_guide

        grabbed = {"called": False}

        def grabber():
            grabbed["called"] = True
            return {"8.1": [{"start": "6:00 PM", "end": "7:00 PM", "title": "PSIP"}]}

        class Held:
            def is_active(self):
                return True

        with tempfile.TemporaryDirectory() as tmp_dir:
            guide_file = os.path.join(tmp_dir, "guide.json")
            result = refresh_guide(
                channels=[{"channel_number": "8.1", "network": "FOX", "callsign": "WJW", "tune_name": "FOX"}],
                guide_path=guide_file,
                grabber=grabber,
                sessions=[Held()],
            )
            self.assertTrue(result["skipped"])
            self.assertFalse(grabbed["called"])
            with open(guide_file, encoding="utf-8") as f:
                data = json.load(f)
            self.assertNotEqual(data["channels"]["8.1"]["programs"][0]["title"], "PSIP")

    def test_refresh_applies_grabber_when_tuner1_free(self):
        from engine.guide import refresh_guide

        with tempfile.TemporaryDirectory() as tmp_dir:
            guide_file = os.path.join(tmp_dir, "guide.json")
            result = refresh_guide(
                channels=[{"channel_number": "8.1", "network": "FOX", "callsign": "WJW", "tune_name": "FOX"}],
                guide_path=guide_file,
                grabber=lambda: {"8.1": [{"start": "9:00 PM", "end": "10:00 PM", "title": "PSIP Night"}]},
                sessions=[],
            )
            self.assertFalse(result["skipped"])
            with open(guide_file, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["channels"]["8.1"]["programs"][0]["title"], "PSIP Night")
            self.assertEqual(data["channels"]["8.1"]["source"], "psip")

    def test_now_and_next_wraps_midnight(self):
        from engine.guide import now_and_next

        programs = [{"start": "11:00 PM", "end": "12:30 AM", "title": "Late"}]
        now, _nxt = now_and_next(programs, now_minutes=15)
        self.assertEqual(now["title"], "Late")

    def test_program_is_on_and_remaining_record_minutes(self):
        from engine.guide import program_is_on, remaining_record_minutes

        block = {"start": "7:00 PM", "end": "8:00 PM", "title": "News"}
        self.assertTrue(program_is_on(block, now_minutes=19 * 60 + 30))
        self.assertEqual(remaining_record_minutes(block, now_minutes=19 * 60 + 30), 30)
        self.assertFalse(program_is_on(block, now_minutes=18 * 60))
        self.assertEqual(remaining_record_minutes(block, now_minutes=18 * 60), 60)
        self.assertIsNone(remaining_record_minutes(block, now_minutes=20 * 60))
        late = {"start": "11:00 PM", "end": "12:30 AM", "title": "Late"}
        self.assertEqual(remaining_record_minutes(late, now_minutes=23 * 60 + 45), 45)

    def test_current_program_title_uses_block_on_now_not_stale_row(self):
        from engine.guide import current_program_title

        row = {
            "title": "Inside Edition",
            "programs": [
                {"start": "7:30 PM", "end": "8:00 PM", "title": "Inside Edition"},
                {"start": "8:00 PM", "end": "8:15 PM", "title": "Monday Night Football Kickoff"},
                {"start": "8:15 PM", "end": "11:15 PM", "title": "Monday Night Football"},
            ],
        }
        self.assertEqual(
            current_program_title(row, now_minutes=20 * 60),
            "Monday Night Football Kickoff",
        )
        self.assertEqual(
            current_program_title(row, now_minutes=19 * 60 + 45),
            "Inside Edition",
        )

    def test_search_guide_shows_neighbors_and_requires_every_word(self):
        from datetime import datetime

        from engine.guide import format_guide_updated, search_guide

        channels = {
            "5.1": {
                "callsign": "WEWSHD",
                "tune_name": "WEWSHD",
                "programs": [
                    {"title": "Inside Edition", "start": "7:30 PM", "end": "8:00 PM"},
                    {
                        "title": "Monday Night Football Kickoff",
                        "start": "8:00 PM",
                        "end": "8:30 PM",
                        "duration_sec": 1800,
                    },
                    {"title": "Monday Night Football", "start": "8:30 PM", "end": "11:30 PM"},
                ],
            },
            "3.1": {
                "callsign": "WKYC",
                "programs": [
                    {"title": "Cleveland Browns", "start": "1:00 PM", "end": "4:00 PM"},
                ],
            },
        }
        hits = search_guide(channels, "night football", now_minutes=20 * 60)
        self.assertEqual(
            [hit["title"] for hit in hits],
            ["Monday Night Football Kickoff", "Monday Night Football"],
        )
        kick = hits[0]
        self.assertTrue(kick["on_now"])
        self.assertEqual(kick["before"]["title"], "Inside Edition")
        self.assertEqual(kick["after"]["title"], "Monday Night Football")
        self.assertFalse(hits[1]["on_now"])
        self.assertEqual(search_guide(channels, "f"), [])
        self.assertEqual(search_guide(channels, "night browns"), [])
        browns = search_guide(channels, "Browns", now_minutes=20 * 60)
        self.assertEqual(browns[0]["channel_number"], "3.1")
        self.assertIsNone(browns[0]["before"])
        self.assertIsNone(browns[0]["after"])
        self.assertFalse(browns[0]["on_now"])

        today = datetime(2026, 9, 21, 21, 0)
        updated = datetime(2026, 9, 21, 19, 30)
        self.assertEqual(
            format_guide_updated(updated.timestamp(), today.timestamp()),
            "Updated 7:30 PM",
        )
        yesterday = datetime(2026, 9, 20, 19, 30)
        self.assertEqual(
            format_guide_updated(yesterday.timestamp(), today.timestamp()),
            "Updated Sep 20, 7:30 PM",
        )
        self.assertEqual(format_guide_updated(None), "Listings have not been updated.")
        self.assertEqual(format_guide_updated(0), "Listings have not been updated.")

    def test_merge_does_not_restore_template_after_psip(self):
        from engine.guide import merge_lineup

        existing = {"8.1": {"source": "psip", "programs": [], "title": "Live"}}
        merged = merge_lineup(
            [{"channel_number": "8.1", "network": "FOX", "callsign": "WJW", "tune_name": "FOX"}],
            existing,
        )
        self.assertEqual(merged["8.1"]["programs"], [])
        self.assertEqual(merged["8.1"]["source"], "psip")


if __name__ == "__main__":
    unittest.main()
