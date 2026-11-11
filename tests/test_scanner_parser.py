"""
Unit tests for scanner output parsing and channel serialization.
"""

import os
import json
import unittest
import tempfile
from unittest.mock import patch
from engine.scanner import AtscScanner, first_pid, parse_scan_transport, write_scan_status

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "scan-tower.ts")


class TestScannerParser(unittest.TestCase):
    def test_parse_saved_transport_stream(self):
        with open(FIXTURE, "rb") as handle:
            data = handle.read()
        channels = parse_scan_transport(data, {
            "channel": 7,
            "frequency": 177028615,
            "band": "VHF-High",
        })
        self.assertEqual(len(channels), 2)
        self.assertEqual(channels[0]["name"], "53.1 Daystar")
        self.assertEqual(channels[0]["service_id"], 1)
        self.assertEqual(channels[0]["frequency"], 177028615)
        self.assertEqual(channels[0]["frequency"] % 1000000, 28615)
        self.assertEqual(channels[0]["video_pid"], 49)
        self.assertEqual(channels[0]["audio_pid"], 52)
        self.assertEqual(channels[0]["major"], 53)
        self.assertEqual(channels[0]["minor"], 1)
        self.assertEqual(channels[1]["name"], "53.2 WCDN")
        self.assertEqual(channels[1]["service_id"], 2)
        self.assertEqual(channels[1]["video_pid"], 65)
        self.assertEqual(channels[1]["audio_pid"], 68)

    def test_audio_pid_keeps_the_first_of_several(self):
        self.assertEqual(first_pid("52 53"), 52)
        self.assertIsInstance(first_pid("52 53"), int)
        with open(FIXTURE, "rb") as handle:
            data = handle.read()
        channels = parse_scan_transport(data, {"channel": 7, "frequency": 177028615, "band": "VHF-High"})
        self.assertEqual(channels[0]["audio_pid"], 52)

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

    def test_scan_does_not_shell_out(self):
        import inspect
        from engine import scanner
        src = inspect.getsource(scanner)
        self.assertNotIn("mktemp", src)
        self.assertNotIn("dvbv5-scan", src)
        self.assertNotIn("subprocess", src)

    def test_scan_uses_work_tuner_and_refuses_when_busy(self):
        scanner = AtscScanner()
        with patch("engine.pool.claims", return_value={}):
            self.assertEqual(scanner._resolve_adapter(), 1)
        with patch("engine.pool.claims", return_value={0: "live", 1: "record"}):
            self.assertEqual(scanner._resolve_adapter(), -1)
        with tempfile.TemporaryDirectory() as tmp:
            status = os.path.join(tmp, "scan_status.json")
            with patch("engine.scanner.SCAN_STATUS_PATH", status), \
                 patch.object(AtscScanner, "_work_tuner_ready", return_value=False):
                events = list(scanner.scan(quick_mode=True))
            self.assertEqual(events[0]["status"], "error")
            self.assertEqual(events[0]["adapter_id"], 1)
            self.assertFalse(events[0]["is_scanning"])
            with open(status, encoding="utf-8") as f:
                self.assertEqual(json.load(f)["status"], "error")

    def _paths(self, tmp):
        return (
            os.path.join(tmp, "scan_status.json"),
            os.path.join(tmp, "channels.json"),
            os.path.join(tmp, "channels.conf"),
        )

    def test_scan_reads_a_tower_fixture(self):
        with open(FIXTURE, "rb") as handle:
            blob = handle.read()
        seen = {"n": 0}

        def read_tower(_adapter, info):
            seen["n"] += 1
            if seen["n"] == 1:
                self.assertEqual(info["frequency"] % 1000000, 28615)
                return blob, 20.0
            return b"", None

        scanner = AtscScanner(adapter_id=1)
        with tempfile.TemporaryDirectory() as tmp:
            status, channels, mpv = self._paths(tmp)
            with patch("engine.scanner.SCAN_STATUS_PATH", status), \
                 patch("engine.scanner.CHANNELS_JSON_PATH", channels), \
                 patch("engine.scanner.MPV_CHANNELS_CONF", mpv), \
                 patch("engine.guide.sync_guide_from_channels"), \
                 patch.object(AtscScanner, "_work_tuner_ready", return_value=True):
                events = list(scanner.scan(quick_mode=True, read_tower=read_tower))
            self.assertEqual(events[0]["status"], "starting")
            self.assertIn("scanning", [ev["status"] for ev in events])
            self.assertEqual(events[-1]["status"], "complete")
            self.assertEqual(events[-1]["total_found"], 2)
            with open(channels, encoding="utf-8") as handle:
                saved = json.load(handle)["channels"]
            self.assertTrue(any("Daystar" in ch.get("name", "") for ch in saved))
            self.assertTrue(all(ch["frequency"] % 1000000 == 28615 for ch in saved))

    def test_interrupted_scan_keeps_the_saved_lineup(self):
        with open(FIXTURE, "rb") as handle:
            blob = handle.read()

        def read_tower(_adapter, _info):
            return blob, 18.0

        scanner = AtscScanner(adapter_id=1)
        with tempfile.TemporaryDirectory() as tmp:
            status, channels, mpv = self._paths(tmp)
            AtscScanner.save_channels(
                [{"name": "KEEP", "frequency": 57028615, "service_id": 3}],
                json_path=channels,
                mpv_path=mpv,
            )
            with patch("engine.scanner.SCAN_STATUS_PATH", status), \
                 patch("engine.scanner.CHANNELS_JSON_PATH", channels), \
                 patch("engine.scanner.MPV_CHANNELS_CONF", mpv), \
                 patch("engine.guide.sync_guide_from_channels"), \
                 patch.object(AtscScanner, "_work_tuner_ready", return_value=True):
                gen = scanner.scan(quick_mode=True, read_tower=read_tower)
                for ev in gen:
                    if ev["status"] == "channel_found":
                        gen.close()
                        break
            with open(channels, encoding="utf-8") as handle:
                saved = [ch.get("name") for ch in json.load(handle)["channels"]]
            with open(mpv, encoding="utf-8") as handle:
                conf = handle.read()
        self.assertEqual(saved, ["KEEP"])
        self.assertIn("KEEP", conf)

    def test_scan_without_a_tower_keeps_the_saved_lineup(self):
        scanner = AtscScanner(adapter_id=1)
        with tempfile.TemporaryDirectory() as tmp:
            status, channels, mpv = self._paths(tmp)
            AtscScanner.save_channels(
                [{"name": "KEEP", "frequency": 57028615, "service_id": 3}],
                json_path=channels,
                mpv_path=mpv,
            )
            with patch("engine.scanner.SCAN_STATUS_PATH", status), \
                 patch("engine.scanner.CHANNELS_JSON_PATH", channels), \
                 patch("engine.scanner.MPV_CHANNELS_CONF", mpv), \
                 patch("engine.guide.sync_guide_from_channels"), \
                 patch.object(AtscScanner, "_work_tuner_ready", return_value=True):
                events = list(scanner.scan(quick_mode=True, read_tower=lambda _a, _i: (b"", None)))
            self.assertEqual(events[-1]["status"], "complete")
            self.assertEqual(events[-1]["total_found"], 0)
            with open(channels, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["channels"][0]["name"], "KEEP")

    def test_scan_failure_returns_to_idle(self):
        scanner = AtscScanner(adapter_id=1)

        def boom(_adapter, _info):
            raise OSError("no frontend")

        with tempfile.TemporaryDirectory() as tmp:
            status = os.path.join(tmp, "scan_status.json")
            with patch("engine.scanner.SCAN_STATUS_PATH", status), \
                 patch.object(AtscScanner, "_work_tuner_ready", return_value=True):
                gen = scanner.scan(quick_mode=True, read_tower=boom)
                self.assertEqual(next(gen)["status"], "starting")
                with self.assertRaises(OSError):
                    next(gen)
            with open(status, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["status"], "idle")


if __name__ == "__main__":
    unittest.main()
