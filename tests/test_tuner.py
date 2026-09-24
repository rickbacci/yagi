"""
Unit tests for TunerManager and TunerAdapter.
"""

import unittest
from unittest.mock import patch

from engine.tuner import (
    LIVE_ADAPTER,
    TunerManager,
    WORK_ADAPTER,
    _FE_READ_SIGNAL_STRENGTH,
    _FE_READ_SNR,
    _FE_READ_STATUS,
    decode_frontend,
)


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

    def test_decode_frontend_snr_is_tenths_of_a_db(self):
        reading = decode_frontend(0x1F, 55704, 200)
        self.assertTrue(reading["locked"])
        self.assertEqual(reading["snr_db"], 20.0)
        self.assertEqual(reading["strength_pct"], 85.0)
        quiet = decode_frontend(0, None, None)
        self.assertFalse(quiet["locked"])
        self.assertIsNone(quiet["snr_db"])

    def test_read_signal_decodes_a_locked_frontend(self):
        def ioctl(_fd, req, buf, _mutate=False):
            if req == _FE_READ_STATUS:
                buf[:4] = (0x1F).to_bytes(4, "little")
            elif req == _FE_READ_SIGNAL_STRENGTH:
                buf[:2] = (55704).to_bytes(2, "little")
            elif req == _FE_READ_SNR:
                buf[:2] = (200).to_bytes(2, "little")

        with patch("engine.tuner.os.path.exists", return_value=True), \
             patch("engine.tuner.os.open", return_value=7), \
             patch("engine.tuner.os.close"), \
             patch("engine.tuner.fcntl.ioctl", side_effect=ioctl):
            reading = TunerManager.read_signal(0)
        self.assertTrue(reading["locked"])
        self.assertEqual(reading["snr_db"], 20.0)
        self.assertEqual(reading["strength_pct"], 85.0)

    def test_read_signal_missing_or_unreadable_is_none(self):
        with patch("engine.tuner.os.path.exists", return_value=False):
            self.assertIsNone(TunerManager.read_signal(0))
        with patch("engine.tuner.os.path.exists", return_value=True), \
             patch("engine.tuner.os.open", side_effect=OSError):
            self.assertIsNone(TunerManager.read_signal(0))

    def test_read_signal_status_failure_is_unlocked(self):
        with patch("engine.tuner.os.path.exists", return_value=True), \
             patch("engine.tuner.os.open", return_value=7), \
             patch("engine.tuner.os.close"), \
             patch("engine.tuner.fcntl.ioctl", side_effect=OSError):
            reading = TunerManager.read_signal(1)
        self.assertFalse(reading["locked"])
        self.assertIsNone(reading["snr_db"])

    def test_read_signal_keeps_lock_when_strength_and_snr_fail(self):
        def ioctl(_fd, req, buf, _mutate=False):
            if req == _FE_READ_STATUS:
                buf[:4] = (0x10).to_bytes(4, "little")
                return
            raise OSError

        with patch("engine.tuner.os.path.exists", return_value=True), \
             patch("engine.tuner.os.open", return_value=7), \
             patch("engine.tuner.os.close"), \
             patch("engine.tuner.fcntl.ioctl", side_effect=ioctl):
            reading = TunerManager.read_signal(0)
        self.assertTrue(reading["locked"])
        self.assertIsNone(reading["strength"])
        self.assertIsNone(reading["snr_db"])

    def test_list_tuners_skips_a_bad_adapter_name(self):
        with patch("engine.tuner.glob.glob", return_value=["/dev/dvb/adapterX"]):
            self.assertEqual(TunerManager.list_tuners(), [])

    def test_job_adapters_are_pinned(self):
        self.assertEqual(LIVE_ADAPTER, 0)
        self.assertEqual(WORK_ADAPTER, 1)
        self.assertFalse(TunerManager.adapter_is_free(99))


if __name__ == "__main__":
    unittest.main()
