"""
Unit tests for TunerManager and TunerAdapter.
"""

import unittest
from engine.tuner import LIVE_ADAPTER, TunerManager, WORK_ADAPTER


def _has_atsc_tuner() -> bool:
    try:
        return any(t.supports_atsc for t in TunerManager.list_tuners())
    except Exception:
        return False


class TestTuner(unittest.TestCase):
    @unittest.skipUnless(_has_atsc_tuner(), "no ATSC adapter on this machine")
    def test_tuner_discovery(self):
        tuners = TunerManager.list_tuners()
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

    def test_job_adapters_are_pinned(self):
        self.assertEqual(LIVE_ADAPTER, 0)
        self.assertEqual(WORK_ADAPTER, 1)
        self.assertFalse(TunerManager.adapter_is_free(99))


if __name__ == "__main__":
    unittest.main()
