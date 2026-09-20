"""
Unit tests for ATSC frequency calculations and pilot carrier offsets.
"""

import unittest
from engine.scanner import get_atsc_frequencies


class TestAtscFrequencies(unittest.TestCase):
    def test_full_scan_count(self):
        freqs = get_atsc_frequencies(quick_mode=False)
        self.assertEqual(len(freqs), 68, "Full ATSC scan must contain 68 physical channels (2-69)")

    def test_quick_scan_count(self):
        freqs = get_atsc_frequencies(quick_mode=True)
        self.assertEqual(len(freqs), 30, "Quick scan must contain 30 channels (7-36)")
        # First should be channel 7, last should be channel 36
        self.assertEqual(freqs[0]["channel"], 7)
        self.assertEqual(freqs[-1]["channel"], 36)

    def test_pilot_carrier_offsets(self):
        """Every ATSC frequency must have the exact +28615 Hz offset for carrier lock."""
        freqs = get_atsc_frequencies(quick_mode=False)
        for entry in freqs:
            freq = entry["frequency"]
            offset = freq % 1000000
            self.assertEqual(
                offset,
                28615,
                f"Channel {entry['channel']} frequency {freq} Hz must end with 28615 Hz offset"
            )

    def test_bands(self):
        freqs = get_atsc_frequencies(quick_mode=False)
        bands = {e["band"] for e in freqs}
        self.assertIn("VHF-Low", bands)
        self.assertIn("VHF-High", bands)
        self.assertIn("UHF", bands)
        self.assertIn("UHF-Extended", bands)


if __name__ == "__main__":
    unittest.main()
