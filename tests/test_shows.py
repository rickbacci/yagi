"""Show rows from Guide airings: pattern, time range, time of day, next airing."""

import unittest
from datetime import datetime

from engine.psip import EASTERN
from engine.shows import build_shows, bucket_for, night_of


def _at(y, m, d, hh, mm=0):
    return int(datetime(y, m, d, hh, mm, tzinfo=EASTERN).timestamp())


def _air(channel, title, start, dur=1800):
    return {"channel": channel, "title": title, "start": start, "duration_sec": dur}


def _by_title(shows):
    return {(s["title"], s["channel"]): s for s in shows}


# Mon 2026-09-21 through Sun 2026-09-27, then the next Wednesday.
MON, TUE, WED, THU, FRI, SAT, SUN = 21, 22, 23, 24, 25, 26, 27


class TestShowRows(unittest.TestCase):
    def test_night_runs_six_to_six_and_buckets(self):
        self.assertEqual(night_of(datetime(2026, 9, 22, 1, 0, tzinfo=EASTERN)).day, MON)
        self.assertEqual(bucket_for(datetime(2026, 9, 21, 21, 0, tzinfo=EASTERN)), "prime")
        self.assertEqual(bucket_for(datetime(2026, 9, 21, 23, 30, tzinfo=EASTERN)), "late")
        self.assertEqual(bucket_for(datetime(2026, 9, 22, 3, 0, tzinfo=EASTERN)), "overnight")
        self.assertEqual(bucket_for(datetime(2026, 9, 22, 14, 0, tzinfo=EASTERN)), "day")

    def test_nightly_and_weeknights(self):
        airings = []
        for day in (MON, TUE, WED, THU, FRI, SAT, SUN):
            airings.append(_air("3.1", "Late News", _at(2026, 9, day, 23)))
        for day in (MON, TUE, WED):
            airings.append(_air("5.1", "Kimmel", _at(2026, 9, day, 23, 35), 3780))
        rows = _by_title(build_shows(airings, now=_at(2026, 9, 28, 12)))
        self.assertEqual(rows[("Late News", "3.1")]["pattern"], "Nightly")
        self.assertEqual(rows[("Late News", "3.1")]["when"], "11 PM–11:30 PM")
        self.assertEqual(rows[("Kimmel", "5.1")]["pattern"], "Weeknights")

    def test_one_night_after_midnight_counts_once(self):
        airings = [
            _air("5.3", "That '70s Show", _at(2026, 9, MON, 23)),
            _air("5.3", "That '70s Show", _at(2026, 9, MON, 23, 30)),
            _air("5.3", "That '70s Show", _at(2026, 9, TUE, 0)),
            _air("5.3", "That '70s Show", _at(2026, 9, TUE, 0, 30)),
        ]
        row = build_shows(airings, now=_at(2026, 9, 20, 12))[0]
        self.assertEqual(row["nights"], 1)
        self.assertEqual(row["pattern"], "Marathon")
        self.assertEqual(row["when"], "11 PM–1 AM")
        self.assertEqual(row["buckets"], ["late"])

    def test_same_weekday_a_week_apart(self):
        airings = [
            _air("8.1", "Monday Night Football", _at(2026, 9, MON, 20, 15), 3 * 3600),
            _air("8.1", "Monday Night Football", _at(2026, 9, 28, 20, 15), 3 * 3600),
        ]
        row = build_shows(airings, now=_at(2026, 9, 20, 12))[0]
        self.assertEqual(row["pattern"], "Mondays")
        self.assertEqual(row["bucket"], "prime")

    def test_day_block_and_late_block_are_separate_rows(self):
        airings = [_air("28.2", "Storage Wars", _at(2026, 9, MON, 14, 0) + i * 1800) for i in range(4)]
        airings += [_air("28.2", "Storage Wars", _at(2026, 9, MON, 23, 0) + i * 1800) for i in range(12)]
        rows = build_shows(airings, now=_at(2026, 9, 20, 12))
        self.assertEqual(sorted(r["bucket"] for r in rows), ["day", "late", "overnight"])
        late = [r for r in rows if r["bucket"] == "late"][0]
        self.assertEqual(late["when"], "11 PM–2 AM")
        self.assertEqual(late["buckets"], ["late"])
        self.assertEqual(late["pattern"], "Marathon")
        overnight = [r for r in rows if r["bucket"] == "overnight"][0]
        self.assertEqual(overnight["when"], "2 AM–5 AM")
        self.assertEqual(len({r["id"] for r in rows}), 1)

    def test_filler_and_hidden_are_left_out(self):
        airings = [
            _air("3.1", "Paid Programming", _at(2026, 9, MON, 3)),
            _air("26.1", "Real Show", _at(2026, 9, MON, 21)),
            _air("3.1", "Real Show", _at(2026, 9, MON, 21)),
        ]
        rows = build_shows(airings, hidden=["26.1"], now=_at(2026, 9, 20, 12))
        self.assertEqual([(r["title"], r["channel"]) for r in rows], [("Real Show", "3.1")])

    def test_next_airing_and_tune_name(self):
        airings = [
            _air("3.3", "George Lopez", _at(2026, 9, MON, 23)),
            _air("3.3", "George Lopez", _at(2026, 9, TUE, 23)),
            _air("3.3", "George Lopez", _at(2026, 9, WED, 23)),
        ]
        row = build_shows(airings, tune_names={"3.3": "WKYC-3"}, now=_at(2026, 9, TUE, 23, 10))[0]
        self.assertEqual(row["tune_name"], "WKYC-3")
        self.assertTrue(row["next"]["on_now"])
        self.assertEqual(row["next"]["start_unix"], _at(2026, 9, TUE, 23))
        after = build_shows(airings, now=_at(2026, 9, WED, 23, 45))[0]
        self.assertIsNone(after["next"])

    def test_rows_sort_by_start_across_midnight(self):
        airings = [
            _air("3.1", "Early Today", _at(2026, 9, TUE, 3)),
            _air("3.1", "Tonight Show", _at(2026, 9, MON, 23, 35)),
            _air("3.1", "Nightly News", _at(2026, 9, MON, 18, 30)),
        ]
        titles = [r["title"] for r in build_shows(airings, now=_at(2026, 9, 20, 12))]
        self.assertEqual(titles, ["Nightly News", "Tonight Show", "Early Today"])


if __name__ == "__main__":
    unittest.main()
