"""Record all: listings join the queue once, at any hour, reruns are skipped, series blurbs are not."""

import json
import os
import tempfile
import unittest
from datetime import datetime

from engine.psip import EASTERN, GPS_LEAP_SECONDS, GPS_UNIX_OFFSET
from engine.rules import add_rule, arm_rules, load_rules, note_recorded, remove_rule
from engine.schedule import load_schedule, remove_later
from engine.shows import show_id


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
        rule = add_rule("That '70s Show", "5.3", "WEWS-3", path=self.rules)
        self.assertEqual(rule["id"], show_id("that 70s show", "5.3"))
        self.assertEqual([r["key"] for r in load_rules(self.rules)], ["that 70s show"])
        self.assertTrue(remove_rule(rule["id"], path=self.rules))
        self.assertFalse(remove_rule(rule["id"], path=self.rules))
        with self.assertRaises(ValueError):
            add_rule("", "5.3", "WEWS-3", path=self.rules)

    def test_queues_matching_airings_once(self):
        rule = add_rule("That '70s Show", "5.3", "WEWS-3", path=self.rules)
        channels = {"5.3": {"display_name": "Laff", "programs": [
            _prog("That '70s Show", _gps(2026, 9, 23, 23), "Eric and Donna plan a road trip to see a concert."),
            _prog("That '70s Show", _gps(2026, 9, 23, 23, 30), "Red takes a job at a hardware store."),
            _prog("George Lopez", _gps(2026, 9, 24, 0)),
        ]}}
        added = self._arm(channels, _now(2026, 9, 23, 22))
        self.assertEqual(len(added), 2)
        queued = load_schedule(self.schedule)
        self.assertEqual(len(queued), 2)
        self.assertTrue(all(row["rule_id"] == rule["id"] for row in queued))
        first, second = sorted(queued, key=lambda r: r["start_unix"])
        self.assertEqual(first["pad_late_sec"], 0)
        self.assertEqual(second["pad_early_sec"], 0)
        self.assertEqual(self._arm(channels, _now(2026, 9, 23, 22, 1)), [])
        remove_later(first["id"], path=self.schedule)
        self.assertEqual(self._arm(channels, _now(2026, 9, 23, 22, 2)), [])
        add_rule("That '70s Show", "5.3", "WEWS-3", path=self.rules)
        self.assertEqual(self._arm(channels, _now(2026, 9, 23, 22, 3)), [])

    def test_a_marathon_across_prime_and_late_queues_every_episode(self):
        add_rule("M*A*S*H", "8.2", "WJW-2", path=self.rules)
        programs = [
            _prog("M*A*S*H", _gps(2026, 9, 23, 19) + i * 1800, f"Episode {i}: Hawkeye and Trapper cause trouble again.")
            for i in range(10)
        ]
        channels = {"8.2": {"programs": programs + [_prog("M*A*S*H", _gps(2026, 9, 23, 7), "A morning airing with its own story.")]}}
        added = self._arm(channels, _now(2026, 9, 23, 18))
        self.assertEqual(len(added), 10)
        self.assertEqual(added[0]["start_unix"], int(_now(2026, 9, 23, 19)))
        self.assertEqual(added[-1]["start_unix"], int(_now(2026, 9, 23, 23, 30)))

    def test_a_show_on_another_channel_is_not_queued(self):
        add_rule("M*A*S*H", "8.2", "WJW-2", path=self.rules)
        channels = {"43.3": {"programs": [_prog("M*A*S*H", _gps(2026, 9, 23, 20))]}}
        self.assertEqual(self._arm(channels, _now(2026, 9, 23, 19)), [])

    def test_skips_a_rerun_but_not_a_shared_series_blurb(self):
        rule = add_rule("Blue Bloods", "23.1", "WVPX", path=self.rules)
        episode = "Frank faces pressure from the mayor over a police shooting downtown."
        series = "A multi-generational family of cops in New York City is put to the test."
        note_recorded(rule["id"], episode, path=self.rules)
        channels = {"23.1": {"programs": [
            _prog("Blue Bloods", _gps(2026, 9, 23, 23), episode, 3600),
            _prog("Blue Bloods", _gps(2026, 9, 24, 0), series, 3600),
            _prog("Blue Bloods", _gps(2026, 9, 24, 1), series, 3600),
        ]}}
        note_recorded(rule["id"], series, path=self.rules)
        added = self._arm(channels, _now(2026, 9, 23, 22))
        self.assertEqual([a["start_unix"] for a in added], [
            int(_now(2026, 9, 24, 0)), int(_now(2026, 9, 24, 1)),
        ])

    def test_a_show_already_on_is_queued_and_an_ended_one_is_not(self):
        add_rule("Late News", "3.1", "WKYC", path=self.rules)
        channels = {"3.1": {"programs": [
            _prog("Late News", _gps(2026, 9, 22, 23)),
            _prog("Late News", _gps(2026, 9, 23, 23)),
        ]}}
        added = self._arm(channels, _now(2026, 9, 23, 23, 10))
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0]["start_unix"], int(_now(2026, 9, 23, 23)))

    def test_an_old_time_of_day_rule_becomes_any_time_on_disk(self):
        old = {"rules": [
            {"id": "66e94a651653", "title": "American Restoration", "key": "american restoration",
             "channel": "28.2", "tune_name": "KONV-LD", "buckets": ["day"],
             "handled": ["KONV-LD-1"], "seen": ["a"], "created": 1},
            {"id": "0123456789ab", "title": "American Restoration", "key": "american restoration",
             "channel": "28.2", "tune_name": "KONV-LD", "buckets": ["late"],
             "handled": ["KONV-LD-2"], "seen": ["b"], "created": 2},
        ]}
        with open(self.rules, "w", encoding="utf-8") as f:
            json.dump(old, f)
        channels = {"28.2": {"programs": [_prog("American Restoration", _gps(2026, 9, 23, 22))]}}
        self.assertEqual(len(self._arm(channels, _now(2026, 9, 23, 21))), 1)
        with open(self.rules, encoding="utf-8") as f:
            saved = json.load(f)["rules"]
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["id"], show_id("american restoration", "28.2"))
        self.assertNotIn("buckets", saved[0])
        self.assertIn("KONV-LD-1", saved[0]["handled"])
        self.assertIn("KONV-LD-2", saved[0]["handled"])
        self.assertEqual(saved[0]["seen"], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
