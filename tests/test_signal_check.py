"""yagi signal check counts the packets the tuner flagged as damaged."""

import contextlib
import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from engine.signal_check import (
    append_block, check, count_damaged, format_block, plan, rf_number, survey, verdict,
)

FOX = {"channel_number": "8.1", "display_name": "FOX", "frequency": 183028615}
RESULT = {"snr": [], "windows": 1, "damaged_windows": 0, "packets": 1, "damaged": 0}


def packet(damaged=False, fill=0):
    return bytes([0x47, 0x80 if damaged else 0x00, 0x11, 0x10]) + bytes([fill]) * 184


class TestSignalCheck(unittest.TestCase):
    def test_flagged_packets_are_counted(self):
        data = packet() + packet(True) + packet() + packet(True)
        self.assertEqual(count_damaged(data), (4, 2, b""))

    def test_a_split_packet_carries_into_the_next_read(self):
        data = packet() + packet(True)
        packets, damaged, carry = count_damaged(data[:300])
        self.assertEqual((packets, damaged, len(carry)), (1, 0, 112))
        self.assertEqual(count_damaged(data[300:], carry)[:2], (1, 1))

    def test_garbage_before_a_packet_is_skipped(self):
        self.assertEqual(count_damaged(b"\x00\x01\x02" + packet(True))[:2], (1, 1))

    def test_the_verdict_reads_the_share_of_damaged_readings(self):
        self.assertEqual(verdict(15, 0), "Clean.")
        self.assertEqual(verdict(15, 1), "A glitch now and then.")
        self.assertEqual(verdict(15, 6), "Damaged often: expect artifacts.")


@patch("engine.signal_check._channel", return_value=FOX)
@patch("engine.signal_check._live_source", return_value=(0, "/x/live.ts"))
@patch("engine.signal_check._follow", return_value=lambda: b"")
@patch("engine.signal_check._watch", return_value=RESULT)
class TestNamedTuner(unittest.TestCase):
    def run_check(self, adapter, claims=None, free=True):
        with patch("engine.signal_check.state_lock", return_value=contextlib.nullcontext()), \
             patch("engine.signal_check.os.path.exists", return_value=True), \
             patch("engine.signal_check.pool.claims", return_value=claims or {}), \
             patch("engine.tuner.TunerManager.adapter_is_free", return_value=free), \
             patch("engine.signal_check.get_runtime_socket", return_value="/x/c.conf"), \
             patch("builtins.open"), patch("engine.signal_check.os.remove"), \
             patch("engine.signal_check.subprocess.Popen") as popen:
            result = check("8.1", seconds=2, say=lambda _: None, adapter=adapter)
        return result, popen

    def test_no_tuner_named_reads_live_tv(self, watch, *_):
        result, popen = self.run_check(None)
        self.assertEqual((result["adapter"], result["live"]), (0, True))
        popen.assert_not_called()

    def test_live_tvs_tuner_reads_live_tv(self, watch, *_):
        result, popen = self.run_check(0)
        self.assertTrue(result["live"])
        popen.assert_not_called()

    def test_the_other_tuner_tunes_it(self, watch, *_):
        result, popen = self.run_check(1)
        self.assertEqual((result["adapter"], result["live"]), (1, False))
        self.assertEqual(popen.call_args[0][0][:3], ["dvbv5-zap", "-a", "1"])

    def test_a_busy_tuner_is_never_taken(self, watch, *_):
        with self.assertRaisesRegex(RuntimeError, "^Tuner 1 is busy recording.$"):
            self.run_check(1, claims={1: "record"})
        with self.assertRaisesRegex(RuntimeError, "^Tuner 1 is busy.$"):
            self.run_check(1, free=False)


LINEUP = {"channels": [
    {"channel_number": "8.1", "display_name": "FOX", "frequency": 183028615},
    {"channel_number": "55.1", "display_name": "CW", "frequency": 183028615},
    {"channel_number": "5.1", "display_name": "ABC", "frequency": 479028615},
    {"channel_number": "43.1", "display_name": "The 43", "frequency": 195028615},
    {"channel_number": "19.1", "display_name": "CBS", "frequency": 195028615},
    {"channel_number": "3.1", "display_name": "NBC", "frequency": 503028615},
    {"channel_number": "19.10", "display_name": "CBS DRT", "frequency": 509028615},
]}
FAVORITES = ["8.1", "5.1", "43.1", "55.1", "3.1", "19.1", "19.10", "7.1"]
WHEN = datetime(2026, 11, 10, 15, 5, tzinfo=ZoneInfo("America/New_York"))


def write_lineup(directory):
    channels = os.path.join(directory, "channels.json")
    favorites = os.path.join(directory, "favorites.json")
    with open(channels, "w", encoding="utf-8") as f:
        json.dump(LINEUP, f)
    with open(favorites, "w", encoding="utf-8") as f:
        json.dump(FAVORITES, f)
    return channels, favorites


class TestSurvey(unittest.TestCase):
    def test_pilot_frequencies_are_rf_channels(self):
        self.assertEqual(
            [rf_number(freq) for freq in (183028615, 195028615, 479028615, 503028615, 509028615)],
            [8, 10, 15, 19, 20],
        )
        self.assertIsNone(rf_number(100))

    def test_favorites_share_a_tower(self):
        with tempfile.TemporaryDirectory() as directory:
            channels, favorites = write_lineup(directory)
            rows, missing = plan("favorites", channels, favorites)
        self.assertEqual(missing, ["7.1"])
        self.assertEqual([row["query"] for row in rows], ["8.1", "5.1", "43.1", "3.1", "19.10"])
        self.assertEqual(rows[0]["also"], ["55.1"])
        self.assertEqual(rows[2]["also"], ["19.1"])
        self.assertEqual([row["rf"] for row in rows], [8, 15, 10, 19, 20])

    def test_all_is_one_row_per_tower_with_favorites_named(self):
        with tempfile.TemporaryDirectory() as directory:
            channels, favorites = write_lineup(directory)
            rows, missing = plan("all", channels, favorites)
        self.assertEqual(missing, [])
        self.assertEqual([row["query"] for row in rows], ["8.1", "43.1", "5.1", "3.1", "19.10"])
        self.assertEqual(rows[0]["also"], ["55.1"])

    def test_the_block_matches_the_log(self):
        text = format_block(
            [({"label": "8.1 FOX", "rf": 8, "band": "VHF", "also": ["55.1"], "frequency": 183028615},
              {"snr": [27.4, 28.2], "damaged": 0, "adapter": 1})],
            "roof, forward", WHEN, 16,
        )
        self.assertEqual(
            text,
            "2026-11-10 15:05 EST  roof, forward\n"
            "  RF 8  VHF   8.1 FOX                27.8 dB (27.4–28.2)    0 damaged  tuner 1  16s  also 55.1\n",
        )

    def test_a_block_is_appended(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "signal-log.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write("old reading\n")
            append_block(path, "new reading\n")
            append_block(path, "third\n")
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "old reading\n\nnew reading\n\nthird\n")

    def test_ctrl_c_keeps_finished_towers(self):
        seen = []

        def fake_check(query, seconds, say, channels_path, adapter):
            seen.append(query)
            return {"snr": [20.0], "windows": 1, "damaged_windows": 0, "packets": 1, "damaged": 0,
                    "adapter": 1, "stopped": query == "5.1"}

        with tempfile.TemporaryDirectory() as directory:
            channels, favorites = write_lineup(directory)
            log = os.path.join(directory, "signal-log.txt")
            with patch("engine.signal_check.check", side_effect=fake_check):
                survey("favorites", say=lambda _line: None, channels_path=channels,
                       favorites_path=favorites, log_path=log, when=WHEN)
            with open(log, encoding="utf-8") as f:
                text = f.read()
        self.assertEqual(seen, ["8.1", "5.1"])
        self.assertIn("stopped", text)
        self.assertIn("8.1 FOX", text)
        self.assertNotIn("NBC", text)

    def test_a_busy_tuner_stops_the_rest(self):
        seen = []

        def fake_check(query, seconds, say, channels_path, adapter):
            seen.append(query)
            if query == "5.1":
                raise RuntimeError("Both tuners are busy.")
            return {"snr": [20.0], "damaged": 0, "adapter": 1, "stopped": False}

        with tempfile.TemporaryDirectory() as directory:
            channels, favorites = write_lineup(directory)
            log = os.path.join(directory, "signal-log.txt")
            with patch("engine.signal_check.check", side_effect=fake_check):
                with self.assertRaisesRegex(RuntimeError, "Both tuners are busy."):
                    survey("favorites", say=lambda _line: None, channels_path=channels,
                           favorites_path=favorites, log_path=log, when=WHEN)
            with open(log, encoding="utf-8") as f:
                text = f.read()
        self.assertEqual(seen, ["8.1", "5.1"])
        self.assertIn("8.1 FOX", text)
        self.assertIn("stopped", text)


if __name__ == "__main__":
    unittest.main()
