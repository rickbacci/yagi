"""ATSC PSIP parse, GPS Eastern labels, Tuner 1 grabber contract."""

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from engine.psip import (
    EASTERN,
    GPS_LEAP_SECONDS,
    GPS_UNIX_OFFSET,
    collect_guide_events,
    format_clock,
    gps_to_datetime,
    pack_eit_section,
    pack_tvct_section,
    parse_atsc_ts,
    section_to_ts,
    unique_frequencies,
)


def gps_for_eastern(year, month, day, hour, minute):
    dt = datetime(year, month, day, hour, minute, tzinfo=EASTERN)
    unix = dt.astimezone(timezone.utc).timestamp()
    return int(unix - GPS_UNIX_OFFSET + GPS_LEAP_SECONDS)


class TestPsip(unittest.TestCase):
    def test_unique_frequencies_keeps_atsc_offset(self):
        freqs = unique_frequencies([
            {"frequency": 183028615, "channel_number": "8.1"},
            {"frequency": 183028615, "channel_number": "55.1"},
            {"frequency": 503028615, "channel_number": "3.1"},
            {"frequency": 0},
        ])
        self.assertEqual(freqs, [183028615, 503028615])
        self.assertTrue(all(f % 1000000 == 28615 for f in freqs))

    def test_gps_to_eastern_label(self):
        gps = gps_for_eastern(2026, 9, 21, 19, 0)
        dt = gps_to_datetime(gps)
        self.assertEqual(dt.tzinfo, EASTERN)
        self.assertEqual(format_clock(dt), "7:00 PM")

    def test_parse_tvct_and_eit_from_fixture_ts(self):
        gps = gps_for_eastern(2026, 9, 21, 19, 0)
        tvct = pack_tvct_section([{
            "short_name": "WJW",
            "major": 8,
            "minor": 1,
            "source_id": 3,
            "program_number": 3,
        }])
        eit = pack_eit_section(3, [{
            "event_id": 11,
            "title": "Local News",
            "gps_start": gps,
            "duration_sec": 1800,
        }])
        ts = section_to_ts(tvct) + section_to_ts(eit)
        programs = parse_atsc_ts(ts)
        self.assertIn("8.1", programs)
        row = programs["8.1"][0]
        self.assertEqual(row["title"], "Local News")
        self.assertEqual(row["start"], "7:00 PM")
        self.assertEqual(row["end"], "7:30 PM")

    def test_collect_skips_when_recording_holds_tuner1(self):
        class Held:
            def is_active(self):
                return True

        called = {"n": 0}

        def dump_fn(adapter, freq):
            called["n"] += 1
            return b""

        events = collect_guide_events(
            channels=[{"frequency": 183028615, "channel_number": "8.1"}],
            dump_fn=dump_fn,
            sessions=[Held()],
        )
        self.assertEqual(events, {})
        self.assertEqual(called["n"], 0)

    def test_collect_parses_dumped_mux(self):
        gps = gps_for_eastern(2026, 9, 21, 20, 0)
        tvct = pack_tvct_section([{
            "short_name": "WJW",
            "major": 8,
            "minor": 1,
            "source_id": 3,
        }])
        eit = pack_eit_section(3, [{
            "title": "FOX Primetime",
            "gps_start": gps,
            "duration_sec": 3600,
        }])
        blob = section_to_ts(tvct) + section_to_ts(eit)

        def dump_fn(adapter, freq):
            self.assertEqual(adapter, 1)
            self.assertEqual(freq, 183028615)
            return blob

        with patch("engine.psip.TunerManager", create=True):
            events = collect_guide_events(
                channels=[{"frequency": 183028615, "channel_number": "8.1"}],
                dump_fn=dump_fn,
                sessions=[],
            )
        self.assertEqual(events["8.1"][0]["title"], "FOX Primetime")
        self.assertEqual(events["8.1"][0]["start"], "8:00 PM")

    def test_dump_mux_records_all_pids(self):
        import inspect
        from engine.psip import dump_mux
        src = inspect.getsource(dump_mux)
        self.assertIn('"-r"', src)
        self.assertIn('"-P"', src)


if __name__ == "__main__":
    unittest.main()
