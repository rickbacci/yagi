"""
Unit tests for scanner output parsing and channel serialization.
"""

import os
import json
import unittest
import tempfile
from engine.scanner import AtscScanner, write_scan_status
from engine.paths import SCAN_STATUS_PATH, CHANNELS_JSON_PATH


class TestScannerParser(unittest.TestCase):
    def test_parse_scan_output(self):
        scanner = AtscScanner()
        test_conf = """
[53.1 Daystar]
  DELIVERY_SYSTEM = ATSC
  FREQUENCY = 177028615
  MODULATION = VSB/8
  SERVICE_ID = 1
  VIDEO_PID = 49
  AUDIO_PID = 52

[53.2 WCDN]
  DELIVERY_SYSTEM = ATSC
  FREQUENCY = 177028615
  MODULATION = VSB/8
  SERVICE_ID = 2
  VIDEO_PID = 65
  AUDIO_PID = 68
"""
        with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as f:
            f.write(test_conf)
            temp_path = f.name

        try:
            channels = scanner._parse_scan_output(temp_path)
            self.assertEqual(len(channels), 2)
            self.assertEqual(channels[0]["name"], "53.1 Daystar")
            self.assertEqual(channels[0]["service_id"], 1)
            self.assertEqual(channels[0]["frequency"], 177028615)
            self.assertEqual(channels[0]["video_pid"], 49)
            self.assertEqual(channels[0]["audio_pid"], 52)
            self.assertEqual(channels[1]["name"], "53.2 WCDN")
            self.assertEqual(channels[1]["service_id"], 2)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_write_scan_status_atomic(self):
        test_status = {
            "is_scanning": True,
            "percent": 42,
            "channel": 18,
            "band": "UHF",
            "frequency": 497028615,
            "signal_dbm": -45.5,
            "total_found": 5
        }
        write_scan_status(test_status)
        self.assertTrue(os.path.exists(SCAN_STATUS_PATH))
        with open(SCAN_STATUS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["percent"], 42)
        self.assertEqual(data["channel"], 18)
        self.assertEqual(data["signal_dbm"], -45.5)

    def test_save_channels(self):
        sample_channels = [
            {"id": "53.1", "name": "53.1 Daystar", "callsign": "Daystar", "frequency": 177028615, "service_id": 1},
            {"id": "53.2", "name": "53.2 WCDN", "callsign": "WCDN", "frequency": 177028615, "service_id": 2}
        ]
        AtscScanner.save_channels(sample_channels)
        self.assertTrue(os.path.exists(CHANNELS_JSON_PATH))
        with open(CHANNELS_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["channels"][0]["name"], "53.1 Daystar")


if __name__ == "__main__":
    unittest.main()
