"""Huffman codec: escape bytes, a stop code, and a truncated stream."""

import unittest

from engine.atsc_huffman import _decode, decode_title, encode

# prior -> {symbol: bits}. 0 ends the string. 27 introduces a raw byte.
_TABLE = {
    0: {65: "0", 27: "10", 0: "11"},
    65: {66: "0", 27: "10", 0: "1"},
    66: {0: "0"},
    126: {0: "0"},
}


class TestHuffman(unittest.TestCase):
    def test_round_trip_and_escape(self):
        self.assertEqual(_decode(_TABLE, encode(_TABLE, "AB")), "AB")
        # 10 = escape, next byte is '~', then 0 ends.
        escaped = bytes([0b10011111, 0b10000000])
        self.assertEqual(_decode(_TABLE, escaped), "~")
        self.assertEqual(_decode(_TABLE, bytes([0b10000000])), "")

    def test_empty_and_truncated_streams_stop(self):
        self.assertEqual(decode_title(b""), "")
        self.assertEqual(_decode(_TABLE, b"\xff"), "")


if __name__ == "__main__":
    unittest.main()
