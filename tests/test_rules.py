"""Record all: listings join the queue once, reruns are skipped, series blurbs are not."""

import os
import tempfile
import unittest
from datetime import datetime

from engine.psip import EASTERN, GPS_LEAP_SECONDS, GPS_UNIX_OFFSET
from engine.rules import add_rule, arm_rules, load_rules, note_recorded, remove_rule
from engine.schedule import load_schedule, remove_later


def _gps(y, m, d, hh, mm=0):
    unix = int(datetime(y, m, d, hh, mm, tzinfo=EASTERN).timestamp())
    return unix - GPS_UNIX_OFFSET + GPS_LEAP_SECONDS


def _now(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=EASTERN).timestamp()


def _prog(title, gps, synopsis="", dur=1800):
    return {"title": title, "gps_start": gps, "duration_sec": dur, "start": "", "end": "", "synopsis": synopsis}


class TestRecordAll(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rules = os.path.join(self.tmp.name, "record_rules.json")
        self.schedule = os.path.join(self.tmp.name, "schedule.json")

    def tearDown(self):
        self.tmp.cleanup()

    def _arm(self, channels, now):
        return arm_rules(channels, now=now, rules_path=self.rules, schedule_path=self.schedule)

    def test_rule_add_and_remove(self):
        add_rule("abc", "That '70s Show", "5.3", "WEWS-3", ["late"], path=self.rules)
        self.assertEqual([r["key"] for r in load_rules(self.rules)], ["that 70s show"])
        self.assertTrue(remove_rule("abc", path=self.rules))
        self.assertFalse(remove_rule("abc", path=self.rules))
        with self.assertRaises(ValueError):
            add_rule("", "x", "5.3", "WEWS-3", [], path=self.rules)

    def test_queues_matching_airings_in_its_time_of_day_once(self):
        add_rule("r1", "That '70s Show", "5.3", "WEWS-3", ["late"], path=self.rules)
        channels = {"5.3": {"display_name": "Laff", "programs": [
            _prog("That '70s Show", _gps(2026, 9, 23, 14)),
            _prog("That '70s Show", _gps(2026, 9, 23, 23), "Eric and Donna plan a road trip to see a concert."),
            _prog("That '70s Show", _gps(2026, 9, 23, 23, 30), "Red takes a job at a hardware store."),
            _prog("George Lopez", _gps(2026, 9, 24, 0)),
        ]}}
        added = self._arm(channels, _now(2026, 9, 23, 22))
        self.assertEqual(len(added), 2)
        queued = load_schedule(self.schedule)
        self.assertEqual(len(queued), 2)
        self.assertTrue(all(row["rule_id"] == "r1" for row in queued))
        first, second = sorted(queued, key=lambda r: r["start_unix"])
        self.assertEqual(first["pad_late_sec"], 0)
        self.assertEqual(second["pad_early_sec"], 0)
        self.assertEqual(self._arm(channels, _now(2026, 9, 23, 22, 1)), [])
        remove_later(first["id"], path=self.schedule)
        self.assertEqual(self._arm(channels, _now(2026, 9, 23, 22, 2)), [])
        add_rule("r1", "That '70s Show", "5.3", "WEWS-3", ["late"], path=self.rules)
        self.assertEqual(self._arm(channels, _now(2026, 9, 23, 22, 3)), [])

    def test_skips_a_rerun_but_not_a_shared_series_blurb(self):
        add_rule("r1", "Blue Bloods", "23.1", "WVPX", ["late", "overnight"], path=self.rules)
        episode = "Frank faces pressure from the mayor over a police shooting downtown."
        series = "A multi-generational family of cops in New York City is put to the test."
        note_recorded("r1", episode, path=self.rules)
        channels = {"23.1": {"programs": [
            _prog("Blue Bloods", _gps(2026, 9, 23, 23), episode, 3600),
            _prog("Blue Bloods", _gps(2026, 9, 24, 0), series, 3600),
            _prog("Blue Bloods", _gps(2026, 9, 24, 1), series, 3600),
        ]}}
        note_recorded("r1", series, path=self.rules)
        added = self._arm(channels, _now(2026, 9, 23, 22))
        self.assertEqual([a["start_unix"] for a in added], [
            int(_now(2026, 9, 24, 0)), int(_now(2026, 9, 24, 1)),
        ])

    def test_a_show_already_on_is_queued_and_an_ended_one_is_not(self):
        add_rule("r1", "Late News", "3.1", "WKYC", ["late"], path=self.rules)
        channels = {"3.1": {"programs": [
            _prog("Late News", _gps(2026, 9, 22, 23)),
            _prog("Late News", _gps(2026, 9, 23, 23)),
        ]}}
        added = self._arm(channels, _now(2026, 9, 23, 23, 10))
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0]["start_unix"], int(_now(2026, 9, 23, 23)))


if __name__ == "__main__":
    unittest.main()
