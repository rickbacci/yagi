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


# The live timer holds the real Tuner 1 lock during a Guide update.
_TUNER_LOCK = patch("engine.pool.LOCK_PREFIX", f"test-tuner-psip-{os.getpid()}-")


def setUpModule():
    _TUNER_LOCK.start()


def tearDownModule():
    _TUNER_LOCK.stop()


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

    def test_collect_stops_when_a_recording_starts_between_towers(self):
        class Held:
            def is_active(self):
                return True

        sessions = []
        towers = []

        def dump_fn(adapter, freq):
            towers.append(freq)
            sessions.append(Held())
            return b""

        collect_guide_events(
            channels=[
                {"frequency": 183028615, "channel_number": "8.1"},
                {"frequency": 503028615, "channel_number": "3.1"},
            ],
            dump_fn=dump_fn,
            sessions=sessions,
        )
        self.assertEqual(len(towers), 1)

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

    def test_ett_description_attaches_to_matching_event(self):
        from engine.psip import pack_ett_section

        gps = gps_for_eastern(2026, 9, 21, 20, 0)
        tvct = pack_tvct_section([{
            "short_name": "WJW",
            "major": 8,
            "minor": 1,
            "source_id": 3,
        }])
        eit = pack_eit_section(3, [{
            "event_id": 11,
            "title": "Local News",
            "gps_start": gps,
            "duration_sec": 1800,
        }])
        ett = pack_ett_section(3, 11, "Weather, sports, and a look at tomorrow.")
        other = pack_ett_section(3, 99, "This belongs to a different show.")
        programs = parse_atsc_ts(section_to_ts(tvct) + section_to_ts(eit) + section_to_ts(ett) + section_to_ts(other))
        row = programs["8.1"][0]
        self.assertEqual(row["synopsis"], "Weather, sports, and a look at tomorrow.")

    def test_repeated_ett_copies_read_once(self):
        from engine.psip import pack_ett_section

        gps = gps_for_eastern(2026, 9, 21, 20, 0)
        tvct = pack_tvct_section([{"short_name": "WKYC", "major": 3, "minor": 1, "source_id": 3}])
        eit = pack_eit_section(3, [{"event_id": 5, "title": "Dateline", "gps_start": gps, "duration_sec": 3600}])
        first = pack_ett_section(3, 5, "Top news anchors report. ", section_number=0, last_section=1)
        second = pack_ett_section(3, 5, "Then the weather.", section_number=1, last_section=1)
        stream = section_to_ts(tvct) + section_to_ts(eit)
        for _ in range(8):
            stream += section_to_ts(first) + section_to_ts(second)
        row = parse_atsc_ts(stream)["3.1"][0]
        self.assertEqual(row["synopsis"], "Top news anchors report. Then the weather.")

    def _multiple_string(self, strings):
        out = bytes([len(strings)])
        for lang, segments in strings:
            out += lang + bytes([len(segments)])
            for mode, chunk in segments:
                out += bytes([0, mode, len(chunk)]) + chunk
        return out

    def test_multiple_string_decodes_unicode_modes(self):
        from engine.psip import parse_multiple_string

        utf16 = self._multiple_string([(b"eng", [(0x3F, "Café Olé".encode("utf-16-be"))])])
        self.assertEqual(parse_multiple_string(utf16), "Café Olé")
        latin_ext = self._multiple_string([(b"eng", [(0x00, b"Pok"), (0x01, bytes([0x5B])), (0x00, b"mon")])])
        self.assertEqual(parse_multiple_string(latin_ext), "Pok\u015bmon")

    def test_multiple_string_prefers_english_over_gluing_languages(self):
        from engine.psip import parse_multiple_string

        both = self._multiple_string([
            (b"spa", [(0x00, b"Noticias")]),
            (b"eng", [(0x00, b"News")]),
        ])
        self.assertEqual(parse_multiple_string(both), "News")
        spanish = self._multiple_string([(b"spa", [(0x00, b"Noticias")])])
        self.assertEqual(parse_multiple_string(spanish), "Noticias")

    def test_listings_follow_the_lineup_when_the_air_numbers_differ(self):
        from engine.psip import lineup_programs

        gps = gps_for_eastern(2026, 9, 23, 22, 0)
        tvct = pack_tvct_section([
            {"short_name": "WAXN", "major": 35, "minor": 4, "source_id": 6, "program_number": 6},
            {"short_name": "WAXN", "major": 35, "minor": 9, "source_id": 9, "program_number": 9},
        ])
        eit = pack_eit_section(6, [{"event_id": 1, "title": "Young Frankenstein", "gps_start": gps, "duration_sec": 6300}])
        other = pack_eit_section(9, [{"event_id": 2, "title": "Unmapped", "gps_start": gps, "duration_sec": 1800}])
        lineup = [
            {"channel_number": "65.4", "frequency": 551028615, "service_id": 6},
            {"channel_number": "65.1", "frequency": 551028615, "service_id": 3},
            {"channel_number": "8.1", "frequency": 183028615, "service_id": 6},
            {"channel_number": "65.8", "frequency": 551028615, "service_id": 3},
        ]
        mapping = lineup_programs(lineup, 551028615)
        self.assertEqual(mapping, {6: "65.4"})
        programs = parse_atsc_ts(section_to_ts(tvct) + section_to_ts(eit) + section_to_ts(other), mapping)
        self.assertEqual(programs["65.4"][0]["title"], "Young Frankenstein")
        self.assertEqual(programs["35.9"][0]["title"], "Unmapped")
        self.assertNotIn("35.4", programs)

    def _pmt(self, program, streams):
        from engine.psip import BitWriter, _private_section
        body = BitWriter()
        body.u(program, 16)
        body.u(3, 2)
        body.u(0, 5)
        body.u(1, 1)
        body.u(0, 8)
        body.u(0, 8)
        body.u(7, 3)
        body.u(streams[0][1], 13)
        body.u(0xF, 4)
        body.u(0, 12)
        for kind, pid in streams:
            body.u(kind, 8)
            body.u(7, 3)
            body.u(pid, 13)
            body.u(0xF, 4)
            body.u(0, 12)
        return _private_section(0x02, body.to_bytes())

    def test_pmt_gives_each_service_its_own_ids(self):
        from engine.psip import parse_pmt_pids
        stream = b""
        for program, streams in (
            (2, [(0x02, 49), (0x81, 52), (0x81, 53)]),
            (3, [(0x02, 65), (0x81, 68)]),
            (4, [(0x02, 81), (0x81, 84)]),
            (9, [(0x81, 200)]),
        ):
            stream += section_to_ts(self._pmt(program, streams), pid=0x30 + program)
        self.assertEqual(parse_pmt_pids(stream), {2: (49, 52), 3: (65, 68), 4: (81, 84)})

    def test_trusted_ids_fix_the_lowest_service_too(self):
        import json
        import tempfile
        from engine.timeshift import Timeshift
        with tempfile.TemporaryDirectory() as tmp:
            conf = os.path.join(tmp, "channels.conf")
            chans = os.path.join(tmp, "channels.json")
            with open(conf, "w", encoding="utf-8") as f:
                f.write("WOIO-HD:195028615:8VSB:65:68:2\n19.2:195028615:8VSB:65:68:3\n"
                        "WUAB:195028615:8VSB:65:68:4\nWEWS:479028615:8VSB:49:52:2\n")
            with open(chans, "w", encoding="utf-8") as f:
                json.dump({"channels": [
                    {"channel_number": "19.1", "frequency": 195028615, "service_id": 2, "video_pid": 65, "audio_pid": 68},
                    {"channel_number": "5.1", "frequency": 479028615, "service_id": 2, "video_pid": 49, "audio_pid": 52},
                ]}, f)
            with patch("engine.timeshift.MPV_CHANNELS_CONF", conf), \
                 patch("engine.timeshift.CHANNELS_JSON_PATH", chans):
                Timeshift._write_learned_pids({2: (49, 52), 3: (65, 68), 4: (81, 84)}, 195028615, trust=True)
            with open(conf, encoding="utf-8") as f:
                lines = f.read().splitlines()
            self.assertEqual(lines, [
                "WOIO-HD:195028615:8VSB:49:52:2",
                "19.2:195028615:8VSB:65:68:3",
                "WUAB:195028615:8VSB:81:84:4",
                "WEWS:479028615:8VSB:49:52:2",
            ])
            with open(chans, encoding="utf-8") as f:
                saved = {c["channel_number"]: (c["video_pid"], c["audio_pid"]) for c in json.load(f)["channels"]}
            self.assertEqual(saved, {"19.1": (49, 52), "5.1": (49, 52)})
            self.assertEqual(oct(os.stat(conf).st_mode & 0o777), "0o600")

    def test_guide_status_is_written_and_a_dead_one_is_cleared(self):
        import json
        import tempfile
        from engine.psip import clear_stale_guide_status, guide_update_running, write_guide_status

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "guide_status.json")
            write_guide_status(True, 2, 9, path=path)
            self.assertTrue(guide_update_running(path))
            self.assertFalse(clear_stale_guide_status(path))
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual((data["tower"], data["towers"], data["pid"]), (2, 9, os.getpid()))
            data["pid"] = 2 ** 22 + 12345
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            self.assertTrue(clear_stale_guide_status(path))
            self.assertFalse(guide_update_running(path))

    def test_description_huffman_roundtrip(self):
        from engine.atsc_huffman import DESCRIPTION, decode_description, encode

        text = "Weather, sports, and a look at tomorrow."
        self.assertEqual(decode_description(encode(DESCRIPTION, text)), text)


if __name__ == "__main__":
    unittest.main()
