"""
Unit tests for TunerManager and TunerAdapter.
"""

import unittest
from unittest.mock import patch

from engine.tuner import (
    TunerManager,
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
        from unittest.mock import MagicMock
        busy = MagicMock(adapter_id=0, supports_atsc=True, is_busy=True)
        other = MagicMock(adapter_id=1, supports_atsc=False, is_busy=False)
        free = MagicMock(adapter_id=2, supports_atsc=True, is_busy=False)
        with patch.object(TunerManager, "list_tuners", return_value=[busy, other, free]):
            self.assertIs(TunerManager.get_available_tuner(require_atsc=True), free)
        with patch.object(TunerManager, "list_tuners", return_value=[busy, other]):
            self.assertIsNone(TunerManager.get_available_tuner(require_atsc=True))

    def test_delivery_systems_come_from_the_frontend_ioctl(self):
        import ctypes
        import struct
        from engine.tuner import (
            _DTV_DELIVERY_SYSTEM,
            _DTV_ENUM_DELSYS,
            _FE_GET_PROPERTY,
            _current_system,
            _delivery_systems,
        )

        def ioctl(_fd, req, arg):
            self.assertEqual(req, _FE_GET_PROPERTY)
            _count, ptr = struct.unpack("<I4xQ", arg)
            cmd = struct.unpack_from("<I", ctypes.string_at(ptr, 4))[0]
            blob = bytearray(76)
            if cmd == _DTV_ENUM_DELSYS:
                struct.pack_into("<III", blob, 16, 3, 11, 16)
                struct.pack_into("<I", blob, 48, 3)
            elif cmd == _DTV_DELIVERY_SYSTEM:
                struct.pack_into("<I", blob, 16, 11)
            else:
                raise AssertionError(cmd)
            ctypes.memmove(ptr, bytes(blob), 76)

        with patch("engine.tuner.fcntl.ioctl", side_effect=ioctl):
            self.assertEqual(_delivery_systems(4), ["DVBT", "ATSC", "DVBT2"])
            self.assertEqual(_current_system(4), "ATSC")

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

    def test_live_takes_the_first_free_tuner_and_other_work_the_last(self):
        from engine.pool import pick_live, pick_work

        self.assertEqual(pick_live({}), 0)
        self.assertEqual(pick_work({}), 1)
        self.assertEqual(pick_live({0: "record"}), 1)
        self.assertEqual(pick_work({1: "live"}), 0)
        self.assertFalse(TunerManager.adapter_is_free(99))


if __name__ == "__main__":
    unittest.main()
