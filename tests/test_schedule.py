"""Waiting-to-record list."""

import os
import tempfile
import time
import unittest

from engine.schedule import add_later, due_items, load_schedule, remove_later, unix_from_gps


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

    def test_due_drops_a_show_that_already_ended(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "schedule.json")
            now = time.time()
            gps = int(now) - (315964800 - 18) - 7200
            add_later("WEWSHD", "Old", gps, 60, path=path)
            self.assertEqual(due_items(now, path), [])
            self.assertEqual(load_schedule(path), [])


if __name__ == "__main__":
    unittest.main()
