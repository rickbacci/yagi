"""Waiting-to-record list."""

import os
import tempfile
import time
import unittest

from engine.schedule import (
    add_later,
    due_items,
    load_schedule,
    pick_due,
    remove_later,
    unix_from_gps,
)


class TestSchedule(unittest.TestCase):
    def test_unix_from_gps_uses_the_leap_offset(self):
        self.assertEqual(unix_from_gps(1), 315964800 - 18 + 1)
        self.assertEqual(unix_from_gps(0), 0)

    def test_add_and_remove(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "schedule.json")
            item = add_later(
                "WEWSHD",
                "News 5",
                1000,
                3600,
                clock="11:00 PM",
                display_name="ABC News 5 (WEWS)",
                path=path,
            )
            self.assertEqual(item["id"], "WEWSHD-1000")
            again = add_later("WEWSHD", "News 5", 1000, 1800, path=path)
            rows = load_schedule(path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(again["duration_sec"], 1800)
            self.assertTrue(remove_later("WEWSHD-1000", path))
            self.assertEqual(load_schedule(path), [])

    def test_due_starts_only_inside_the_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "schedule.json")
            now = time.time()
            # gps such that unix start is 30s ago
            gps = int(now) - (315964800 - 18) - 30
            add_later("WEWSHD", "News 5", gps, 3600, path=path)
            future_gps = int(now) - (315964800 - 18) + 3600
            add_later("WKYC-HD", "Later", future_gps, 1800, path=path)
            ready = due_items(now, path)
            self.assertEqual([row["tune_name"] for row in ready], ["WEWSHD"])
            self.assertEqual(len(load_schedule(path)), 2)

    def test_due_starts_a_minute_early(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "schedule.json")
            now = time.time()
            gps = int(now) - (315964800 - 18) + 30
            add_later("WEWSHD", "News 5", gps, 3600, path=path)
            ready = due_items(now, path)
            self.assertEqual([row["tune_name"] for row in ready], ["WEWSHD"])

    def test_extra_end_keeps_a_game_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "schedule.json")
            now = time.time()
            gps = int(now) - (315964800 - 18) - 300
            add_later("WEWSHD", "Football", gps, 60, extra_end_sec=180, path=path)
            self.assertEqual(len(due_items(now, path)), 1)

    def test_due_keeps_a_show_that_never_started(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "schedule.json")
            now = time.time()
            gps = int(now) - (315964800 - 18) - 7200
            add_later("WEWSHD", "Old", gps, 60, path=path)
            self.assertEqual(due_items(now, path), [])
            rows = load_schedule(path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "missed")
            self.assertEqual(due_items(now + 21 * 3600, path), [])
            self.assertEqual(len(load_schedule(path)), 1)
            due_items(now + 23 * 3600, path)
            self.assertEqual(load_schedule(path), [])

    def test_pick_due_runs_one_show(self):
        ready = [{"id": "a", "title": "First"}, {"id": "b", "title": "Second"}]
        self.assertEqual(pick_due(ready, False)["id"], "a")
        self.assertIsNone(pick_due(ready, True))
        self.assertEqual(len(ready), 2)

    def test_schedule_file_is_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "tv", "schedule.json")
            add_later("WEWSHD", "News 5", 1000, 3600, path=path)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(os.path.dirname(path)).st_mode & 0o777, 0o700)


if __name__ == "__main__":
    unittest.main()
