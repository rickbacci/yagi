"""yagi signal check counts the packets the tuner flagged as damaged."""

import contextlib
import unittest
from unittest.mock import patch

from engine.signal_check import check, count_damaged, verdict

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


if __name__ == "__main__":
    unittest.main()
