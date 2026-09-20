"""
Contract and schema validation tests for Omarchy TV.
Ensures IPC and state file boundaries between Python engine and Quickshell UI never break.
"""

import os
import json
import time
import unittest
import tempfile
from typing import Dict, Any, List

from engine.scanner import AtscScanner, write_scan_status


class SchemaValidator:
    """Zero-dependency schema and invariant validator for Omarchy TV IPC files."""

    @staticmethod
    def validate_channels_json(data: Dict[str, Any]) -> List[str]:
        errors = []
        if not isinstance(data, dict):
            return ["Root must be a JSON object"]

        if "updated_at" not in data or not isinstance(data["updated_at"], (int, float)):
            errors.append("Missing or invalid 'updated_at' (must be timestamp number)")

        if "total" not in data or not isinstance(data["total"], int) or data["total"] < 0:
            errors.append("Missing or invalid 'total' (must be non-negative integer)")

        if "channels" not in data or not isinstance(data["channels"], list):
            errors.append("Missing or invalid 'channels' (must be array)")
        else:
            if len(data["channels"]) != data.get("total", -1):
                errors.append(f"channels length ({len(data['channels'])}) does not match total ({data.get('total')})")

            for i, ch in enumerate(data["channels"]):
                if not isinstance(ch, dict):
                    errors.append(f"channels[{i}] must be an object")
                    continue
                for req_key in ["name", "frequency"]:
                    if req_key not in ch:
                        errors.append(f"channels[{i}] missing required field '{req_key}'")
                if "name" in ch and not isinstance(ch["name"], str):
                    errors.append(f"channels[{i}].name must be string")
                if "frequency" in ch and not isinstance(ch["frequency"], int):
                    errors.append(f"channels[{i}].frequency must be integer")

        return errors

    @staticmethod
    def validate_scan_status_json(data: Dict[str, Any]) -> List[str]:
        errors = []
        if not isinstance(data, dict):
            return ["Root must be a JSON object"]

        if "is_scanning" not in data or not isinstance(data["is_scanning"], bool):
            errors.append("Missing or invalid 'is_scanning' (must be boolean)")

        if "percent" not in data or not isinstance(data["percent"], int) or not (0 <= data["percent"] <= 100):
            errors.append("Missing or invalid 'percent' (must be integer 0-100)")

        if "total_found" not in data or not isinstance(data["total_found"], int) or data["total_found"] < 0:
            errors.append("Missing or invalid 'total_found' (must be non-negative integer)")

        if "updated_at" not in data or not isinstance(data["updated_at"], (int, float)):
            errors.append("Missing or invalid 'updated_at' (must be timestamp number)")

        if data.get("signal_dbm") is not None and not isinstance(data.get("signal_dbm"), (int, float)):
            errors.append("Field 'signal_dbm' must be number or null")

        return errors


class TestContracts(unittest.TestCase):
    def test_save_channels_contract(self):
        """AtscScanner.save_channels must strictly adhere to channels.json schema."""
        sample_channels = [
            {
                "id": "53.1",
                "name": "53.1 Daystar",
                "callsign": "Daystar",
                "physical_channel": 7,
                "frequency": 177028615,
                "band": "VHF-High",
                "service_id": 1
            },
            {
                "id": "8.1",
                "name": "8.1 FOX",
                "callsign": "FOX",
                "physical_channel": 8,
                "frequency": 183028615,
                "band": "VHF-High",
                "service_id": 1
            }
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            ch_json = os.path.join(tmp_dir, "channels.json")
            mpv_conf = os.path.join(tmp_dir, "channels.conf")

            AtscScanner.save_channels(sample_channels, json_path=ch_json, mpv_path=mpv_conf)

            with open(ch_json, "r", encoding="utf-8") as f:
                data = json.load(f)

            errors = SchemaValidator.validate_channels_json(data)
            self.assertEqual(errors, [], f"Schema validation failed: {errors}")
            self.assertEqual(data["total"], 2)
            self.assertGreater(data["updated_at"], 0)

    def test_write_scan_status_contract(self):
        """write_scan_status must strictly adhere to scan_status.json schema."""
        status_payload = {
            "status": "scanning",
            "is_scanning": True,
            "index": 12,
            "total": 30,
            "percent": 40,
            "channel": 18,
            "frequency": 497028615,
            "band": "UHF",
            "signal_dbm": -38.5,
            "total_found": 15,
            "channels": []
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            status_path = os.path.join(tmp_dir, "scan_status.json")
            write_scan_status(status_payload, status_path=status_path)

            with open(status_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            errors = SchemaValidator.validate_scan_status_json(data)
            self.assertEqual(errors, [], f"Schema validation failed: {errors}")
            self.assertIn("updated_at", data)
            self.assertAlmostEqual(data["updated_at"], time.time(), delta=3.0)

    def test_heartbeat_staleness_detection(self):
        """Verify heartbeat contract: status older than 15s must be detectable as stale."""
        stale_status = {
            "is_scanning": True,
            "percent": 42,
            "total_found": 2,
            "updated_at": time.time() - 30.0  # 30 seconds ago
        }

        now = time.time()
        is_stale = (now - stale_status["updated_at"]) > 15.0
        self.assertTrue(is_stale, "Status older than 15 seconds must be flagged as stale")


if __name__ == "__main__":
    unittest.main()
