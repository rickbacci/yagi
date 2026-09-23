"""
Unit tests for Omarchy TV - Electronic Program Guide (EPG)
"""

import os
import json
import unittest
import tempfile
from engine.guide import load_guide, save_default_guide, get_channel_program


GUIDE_FIXTURE = {
    "3.1": {
        "network": "NBC",
        "station": "WKYC-HD",
        "title": "NBC Nightly News with Lester Holt",
        "start_time": "6:30 PM",
        "end_time": "7:00 PM",
        "next_title": "Local News at 7:00 PM",
    },
    "5.1": {
        "network": "ABC",
        "station": "WEWSHD",
        "title": "World News",
        "start_time": "6:30 PM",
        "end_time": "7:00 PM",
    },
    "8.1": {
        "network": "FOX",
        "station": "FOX",
        "title": "FOX 8 News at 6:00 PM",
        "start_time": "6:00 PM",
        "end_time": "7:00 PM",
    },
    "61.1": {
        "network": "Univision",
        "station": "WQHS-DT",
        "title": "Noticiero Univision",
        "start_time": "6:30 PM",
        "end_time": "7:00 PM",
    },
}


class TestGuide(unittest.TestCase):
    def test_default_guide_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            guide_file = os.path.join(tmp_dir, "guide.json")
            data = save_default_guide(guide_path=guide_file)
            self.assertTrue(os.path.exists(guide_file))
            self.assertEqual(data["channels"], {})
            self.assertEqual(data["updated_at"], 0)

    def test_missing_guide_does_not_invent_listings(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            guide_file = os.path.join(tmp_dir, "guide.json")
            data = load_guide(guide_path=guide_file)
            self.assertEqual(data["channels"], {})
            self.assertIsNone(get_channel_program("3.1", guide_data=data))
            self.assertIsNone(get_channel_program("FOX", guide_data=data))

    def test_load_guide_leaves_a_now_next_row_alone(self):
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
            self.assertEqual(data["channels"]["8.1"].get("programs") or [], [])
            with open(guide_file, encoding="utf-8") as f:
                on_disk = json.load(f)
            self.assertEqual(on_disk["channels"]["8.1"].get("programs") or [], [])
            fox_prog = get_channel_program("FOX", guide_data=data)
            self.assertEqual(fox_prog["network"], "FOX")
            abc_prog = get_channel_program("ABC", guide_data=data)
            self.assertIsNone(abc_prog)

    def test_get_timeline_grid(self):
        from engine.guide import get_timeline_grid
        grid = get_timeline_grid(guide_data={"channels": GUIDE_FIXTURE})
        self.assertIn("slots", grid)
        self.assertIn("rows", grid)
        self.assertGreater(len(grid["rows"]), 0)
        self.assertEqual(grid["rows"][0]["channel_number"], "3.1")
        empty = get_timeline_grid(guide_data={"channels": {}})
        self.assertEqual(empty["rows"], [])

    def test_get_slot_program_now_and_next(self):
        from engine.guide import get_slot_program

        nbc = GUIDE_FIXTURE["3.1"]
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
        from engine.guide import match_guide_program

        fox = match_guide_program({"name": "FOX", "raw_name": "FOX"}, GUIDE_FIXTURE)
        self.assertIsNotNone(fox)
        self.assertEqual(fox["network"], "FOX")

        nbc = match_guide_program({"name": "WKYC-HD", "raw_name": "WKYC-HD"}, GUIDE_FIXTURE)
        self.assertEqual(nbc["title"], GUIDE_FIXTURE["3.1"]["title"])

        uni = match_guide_program({"name": "WQHS-DT", "tune_name": "WQHS-DT"}, GUIDE_FIXTURE)
        self.assertEqual(uni["network"], "Univision")

        numbered = match_guide_program({"name": "FOX", "channel_number": "5.1"}, GUIDE_FIXTURE)
        self.assertEqual(numbered["network"], "ABC")

    def test_engine_has_no_canned_lineup(self):
        src = os.path.join(os.path.dirname(os.path.dirname(__file__)), "engine", "guide.py")
        with open(src, encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("BROADCAST_SCHEDULES", text)
        self.assertNotIn("Lester Holt", text)
        self.assertNotIn("_ensure_programs", text)

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
        self.assertEqual(merged["8.1"]["programs"], [])
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
            self.assertEqual(data["channels"]["8.1"]["programs"], [])

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

    def test_now_and_next_ignores_yesterdays_clock(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        from engine.guide import now_and_next, program_is_on, remaining_record_minutes

        game = {
            "title": "Monday Night Football",
            "start": "8:15 PM",
            "end": "11:15 PM",
            "gps_start": 1474071318,
            "duration_sec": 10800,
        }
        eastern = ZoneInfo("America/New_York")
        during = datetime(2026, 9, 21, 22, 50, tzinfo=eastern).timestamp()
        tonight = datetime(2026, 9, 22, 22, 54, tzinfo=eastern).timestamp()
        now, _nxt = now_and_next([game], now_minutes=22 * 60 + 54, now_unix=during)
        self.assertEqual(now["title"], "Monday Night Football")
        self.assertTrue(program_is_on(game, now_unix=during))
        later, _nxt = now_and_next([game], now_minutes=22 * 60 + 54, now_unix=tonight)
        self.assertIsNone(later)
        self.assertFalse(program_is_on(game, now_minutes=22 * 60 + 54, now_unix=tonight))
        self.assertIsNone(remaining_record_minutes(game, now_minutes=22 * 60 + 54, now_unix=tonight))

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

    def test_two_weeks_says_when_a_show_usually_airs(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from engine.psip import GPS_LEAP_SECONDS, GPS_UNIX_OFFSET
        from engine.guide import _load_history, delete_airing, remember_guide_history

        eastern = ZoneInfo("America/New_York")

        def gps(when):
            return int(when.timestamp()) - GPS_UNIX_OFFSET + GPS_LEAP_SECONDS

        def football(when):
            return {
                "station": "WEWSHD",
                "programs": [
                    {"title": "Kickoff", "start": "8:00 PM", "gps_start": gps(when.replace(minute=0))},
                    {
                        "title": "Monday Night Football",
                        "start": "8:15 PM",
                        "end": "11:15 PM",
                        "gps_start": gps(when),
                    },
                    {
                        "title": "News 5",
                        "start": "11:15 PM",
                        "gps_start": gps(when.replace(hour=23, minute=15)),
                    },
                ],
            }

        first = datetime(2026, 9, 14, 20, 15, tzinfo=eastern)
        second = datetime(2026, 9, 21, 20, 15, tzinfo=eastern)
        stale = datetime(2026, 7, 1, 20, 15, tzinfo=eastern)
        now = datetime(2026, 9, 21, 21, 0, tzinfo=eastern).timestamp()

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "guide_history.json")
            once = {"5.1": football(first)}
            remember_guide_history(once, path, now=now)
            self.assertEqual(once["5.1"]["programs"][1].get("usual", ""), "")

            again = {
                "5.1": football(second),
                "19.1": {
                    "station": "WOIO",
                    "programs": [{
                        "title": "Evening News",
                        "start": "8:15 PM",
                        "gps_start": gps(second),
                    }],
                },
            }
            history = remember_guide_history(again, path, now=now)
            show = again["5.1"]["programs"][1]
            self.assertEqual(show["usual"], "Usually Mondays at 8:15 PM")
            self.assertNotIn("also", show)
            slot = next(item for item in history["usual"] if item["title"] == "Monday Night Football")
            self.assertEqual(len(slot["weeks"]), 2)
            self.assertEqual(slot["duration_sec"], 3 * 3600)

            remembered = remember_guide_history({"5.1": football(second)}, path, now=now)
            slot = next(item for item in remembered["usual"] if item["title"] == "Monday Night Football")
            self.assertEqual(len(slot["weeks"]), 2)
            football_airings = [
                item for item in remembered["airings"] if item["title"] == "Monday Night Football"
            ]
            self.assertEqual(len(football_airings), 2)

            aged = remember_guide_history(
                {"5.1": football(stale) | {"programs": [{
                    "title": "Ancient Show",
                    "start": "8:15 PM",
                    "gps_start": gps(stale),
                }]}},
                path,
                now=now,
            )
            self.assertNotIn("Ancient Show", [item["title"] for item in aged["airings"]])
            month_old = datetime(2026, 9, 1, 20, 15, tzinfo=eastern)
            kept = remember_guide_history(
                {"5.1": {"station": "WEWSHD", "programs": [{
                    "title": "Still Here",
                    "start": "8:15 PM",
                    "end": "9:15 PM",
                    "gps_start": gps(month_old),
                }]}},
                path,
                now=now,
            )
            self.assertIn("Still Here", [item["title"] for item in kept["airings"]])
            self.assertTrue(delete_airing("5.1", int(month_old.timestamp()), path))
            left = _load_history(path)
            self.assertNotIn("Still Here", [item["title"] for item in left["airings"]])
            self.assertIn("Monday Night Football", [item["title"] for item in left["airings"]])

    def test_mash_titles_share_a_slot_and_a_mark_records_once(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from engine.psip import GPS_LEAP_SECONDS, GPS_UNIX_OFFSET
        from engine.guide import (
            _fold_title,
            _load_history,
            add_slot,
            arm_weekly_slots,
            delete_slot,
            listed_slots,
            remember_guide_history,
            rename_slot,
            set_slot_aliases,
            set_slot_clock,
            set_slot_length,
            set_slot_record,
        )
        from engine.schedule import load_schedule

        self.assertEqual(_fold_title("M*A*S*H"), "mash")
        self.assertEqual(_fold_title("MASH"), "mash")
        eastern = ZoneInfo("America/New_York")

        def gps(when):
            return int(when.timestamp()) - GPS_UNIX_OFFSET + GPS_LEAP_SECONDS

        def show(when, title):
            return {"5.1": {"station": "WEWSHD", "programs": [{
                "title": title,
                "start": "8:15 PM",
                "end": "8:45 PM",
                "gps_start": gps(when),
            }]}}

        first = datetime(2026, 9, 14, 20, 15, tzinfo=eastern)
        second = datetime(2026, 9, 21, 20, 15, tzinfo=eastern)
        now = second.timestamp()
        with tempfile.TemporaryDirectory() as tmp:
            hist = os.path.join(tmp, "guide_history.json")
            sched = os.path.join(tmp, "schedule.json")
            remember_guide_history(show(first, "M*A*S*H"), hist, now=now)
            history = remember_guide_history(show(second, "MASH"), hist, now=now)
            mash = [slot for slot in history["usual"] if _fold_title(slot["title"]) == "mash"]
            self.assertEqual(len(mash), 1)
            self.assertEqual(mash[0]["duration_sec"], 30 * 60)
            self.assertEqual(len(listed_slots(history)), 1)
            renamed = rename_slot(mash[0]["id"], "MASH", hist)
            self.assertEqual(renamed["title"], "MASH")
            moved = set_slot_clock(mash[0]["id"], "8:00 PM", hist)
            self.assertEqual(moved["clock"], "8:00 PM")
            sized = set_slot_length(mash[0]["id"], 1800, hist)
            self.assertEqual(sized["duration_sec"], 1800)
            self.assertTrue(sized["length_locked"])
            set_slot_aliases(mash[0]["id"], ["MNF"], hist)
            set_slot_record(mash[0]["id"], True, hist)
            added = add_slot("8.1", "News", 0, "6:00 PM", 1800, tune_name="WJW-HD", history_path=hist)
            self.assertTrue(any(slot["id"] == added["id"] for slot in listed_slots(_load_history(hist))))
            queued = arm_weekly_slots(now, hist, sched)
            self.assertEqual(len(queued), 1)
            self.assertEqual(queued[0]["slot_id"], mash[0]["id"])
            self.assertEqual(arm_weekly_slots(now, hist, sched), [])
            self.assertTrue(_load_history(hist)["usual"][0]["record"])
            self.assertEqual(len(load_schedule(sched)), 1)
            self.assertTrue(delete_slot(added["id"], hist))

    def test_guide_grab_waits_for_a_free_tuner_and_a_few_hours(self):
        from engine.guide import guide_grab_due

        now = 1_000_000.0
        self.assertFalse(guide_grab_due(now, now - 100, True))
        self.assertFalse(guide_grab_due(now, now - 100, False))
        self.assertTrue(guide_grab_due(now, now - 6 * 3600, False))
        self.assertTrue(guide_grab_due(now, 0, False))


if __name__ == "__main__":
    unittest.main()
