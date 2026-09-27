"""yagi signal check counts the packets the tuner flagged as damaged."""

import unittest

from engine.signal_check import count_damaged, verdict


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


if __name__ == "__main__":
    unittest.main()
