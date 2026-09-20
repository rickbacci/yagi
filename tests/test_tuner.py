"""
Unit tests for TunerManager and TunerAdapter.
"""

import unittest
from engine.tuner import TunerManager, TunerAdapter


class TestTuner(unittest.TestCase):
    def test_tuner_discovery(self):
        tuners = TunerManager.list_tuners()
        # On this machine, there are 2 tuners (Hauppauge WinTV-dualHD)
        self.assertGreaterEqual(len(tuners), 1)
        for t in tuners:
            self.assertIn("ATSC", t.delivery_systems)
            self.assertTrue(t.supports_atsc)
            d = t.to_dict()
            self.assertIn("adapter_id", d)
            self.assertIn("is_busy", d)
            self.assertIn("delivery_systems", d)

    def test_get_available_tuner(self):
        # Must return an adapter or None without throwing an exception
        tuner = TunerManager.get_available_tuner(require_atsc=True)
        if tuner:
            self.assertTrue(tuner.supports_atsc)
            self.assertFalse(tuner.is_busy)


if __name__ == "__main__":
    unittest.main()
