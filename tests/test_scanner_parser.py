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
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_status_path = os.path.join(tmp_dir, "scan_status.json")
            write_scan_status(test_status, status_path=test_status_path)
            self.assertTrue(os.path.exists(test_status_path))
            with open(test_status_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["percent"], 42)
            self.assertEqual(data["channel"], 18)
            self.assertEqual(data["signal_dbm"], -45.5)

    def test_save_channels(self):
        sample_channels = [
            {"id": "53.1", "name": "53.1 Daystar", "callsign": "Daystar", "frequency": 177028615, "service_id": 1},
            {"id": "53.2", "name": "53.2 WCDN", "callsign": "WCDN", "frequency": 177028615, "service_id": 2}
        ]
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_json_path = os.path.join(tmp_dir, "channels.json")
            test_mpv_path = os.path.join(tmp_dir, "channels.conf")
            AtscScanner.save_channels(sample_channels, json_path=test_json_path, mpv_path=test_mpv_path)
            self.assertTrue(os.path.exists(test_json_path))
            with open(test_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["total"], 2)
            self.assertEqual(data["channels"][0]["name"], "53.1 Daystar")
            self.assertTrue(os.path.exists(test_mpv_path))

    def test_empty_scan_does_not_replace_a_saved_lineup(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            test_json_path = os.path.join(tmp_dir, "channels.json")
            test_mpv_path = os.path.join(tmp_dir, "channels.conf")
            with open(test_json_path, "w", encoding="utf-8") as f:
                f.write('{"total": 1, "channels": [{"name": "KEEP"}]}')
            with open(test_mpv_path, "w", encoding="utf-8") as f:
                f.write("KEEP:1:8VSB:1:1:1\n")
            saved = AtscScanner.commit_discovered([], json_path=test_json_path, mpv_path=test_mpv_path)
            self.assertFalse(saved)
            with open(test_json_path, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["channels"][0]["name"], "KEEP")
            with open(test_mpv_path, encoding="utf-8") as f:
                self.assertIn("KEEP", f.read())


if __name__ == "__main__":
    unittest.main()
