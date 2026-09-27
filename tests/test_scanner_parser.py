"""
Unit tests for scanner output parsing and channel serialization.
"""

import os
import json
import unittest
import tempfile
from unittest.mock import patch
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

    def test_scan_does_not_use_mktemp(self):
        import inspect
        from engine import scanner
        src = inspect.getsource(scanner)
        self.assertNotIn("mktemp", src)
        self.assertIn("NamedTemporaryFile", src)

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

    def test_scan_reads_a_fake_dvbv5_scan(self):
        class FakeProc:
            def __init__(self, cmd, **_kwargs):
                out = cmd[cmd.index("-o") + 1]
                with open(out, "w", encoding="utf-8") as handle:
                    handle.write(
                        "[3.4 Quest]\n"
                        "  DELIVERY_SYSTEM = ATSC\n"
                        "  FREQUENCY = 57028615\n"
                        "  SERVICE_ID = 4\n"
                        "  VIDEO_PID = 49\n"
                        "  AUDIO_PID = 52\n"
                    )
                self.stdout = [
                    "\n",
                    "Scanning frequency #1 57028615\n",
                    "Signal= -40.5dBm\n",
                    "Signal= nope\n",
                    "Scanning frequency #nope\n",
                    "Virtual channel 3.4, name = Quest\n",
                    "Service Extra, Provider X\n",
                ]

            def wait(self):
                return 0

        scanner = AtscScanner(adapter_id=1)
        with tempfile.TemporaryDirectory() as tmp:
            status = os.path.join(tmp, "scan_status.json")
            channels = os.path.join(tmp, "channels.json")
            mpv = os.path.join(tmp, "channels.conf")
            with patch("engine.scanner.SCAN_STATUS_PATH", status), \
                 patch("engine.scanner.CHANNELS_JSON_PATH", channels), \
                 patch("engine.scanner.MPV_CHANNELS_CONF", mpv), \
                 patch("engine.guide.sync_guide_from_channels"), \
                 patch.object(AtscScanner, "_work_tuner_ready", return_value=True), \
                 patch("engine.scanner.subprocess.Popen", side_effect=FakeProc):
                events = list(scanner.scan(quick_mode=True, timeout_multiplier=1))
            self.assertEqual(events[0]["status"], "starting")
            self.assertIn("scanning", [ev["status"] for ev in events])
            self.assertEqual(events[-1]["status"], "complete")
            self.assertGreaterEqual(events[-1]["total_found"], 1)
            with open(channels, encoding="utf-8") as handle:
                saved = json.load(handle)["channels"]
            self.assertTrue(any("Quest" in ch.get("name", "") for ch in saved))

    def _fake_scan_proc(self, conf_text, lines):
        test = self

        class FakeProc:
            instances = []

            def __init__(self, cmd, **_kwargs):
                out = cmd[cmd.index("-o") + 1]
                with open(out, "w", encoding="utf-8") as handle:
                    handle.write(conf_text)
                self.stdout = list(lines)
                self.returncode = None
                self.terminated = False
                FakeProc.instances.append(self)

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                if self.returncode is None:
                    self.returncode = 0
                return self.returncode

            def terminate(self):
                self.terminated = True
                self.returncode = -15

            def kill(self):
                self.returncode = -9

        return FakeProc

    def _scan_with(self, fake, tmp, stop_after=None):
        scanner = AtscScanner(adapter_id=1)
        status = os.path.join(tmp, "scan_status.json")
        channels = os.path.join(tmp, "channels.json")
        mpv = os.path.join(tmp, "channels.conf")
        AtscScanner.save_channels(
            [{"name": "KEEP", "frequency": 57028615, "service_id": 3}],
            json_path=channels,
            mpv_path=mpv,
        )
        with patch("engine.scanner.SCAN_STATUS_PATH", status), \
             patch("engine.scanner.CHANNELS_JSON_PATH", channels), \
             patch("engine.scanner.MPV_CHANNELS_CONF", mpv), \
             patch("engine.guide.sync_guide_from_channels"), \
             patch.object(AtscScanner, "_work_tuner_ready", return_value=True), \
             patch("engine.scanner.subprocess.Popen", side_effect=fake):
            gen = scanner.scan(quick_mode=True)
            for ev in gen:
                if stop_after and ev["status"] == stop_after:
                    gen.close()
                    break
        with open(channels, encoding="utf-8") as handle:
            saved = [ch.get("name") for ch in json.load(handle)["channels"]]
        with open(mpv, encoding="utf-8") as handle:
            conf = handle.read()
        return saved, conf

    def test_interrupted_scan_keeps_the_saved_lineup(self):
        fake = self._fake_scan_proc("", [
            "Scanning frequency #1 57028615\n",
            "Virtual channel 3.4, name = Quest\n",
            "Scanning frequency #2 63028615\n",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            saved, conf = self._scan_with(fake, tmp, stop_after="channel_found")
        self.assertEqual(saved, ["KEEP"])
        self.assertIn("KEEP", conf)
        self.assertTrue(fake.instances[0].terminated)

    def test_scan_without_finished_output_keeps_the_saved_lineup(self):
        fake = self._fake_scan_proc("", [
            "Scanning frequency #1 57028615\n",
            "Virtual channel 3.4, name = Quest\n",
        ])
        with tempfile.TemporaryDirectory() as tmp:
            saved, conf = self._scan_with(fake, tmp)
        self.assertEqual(saved, ["KEEP"])
        self.assertNotIn("Quest", conf)

    def test_scan_failure_returns_to_idle(self):
        scanner = AtscScanner(adapter_id=1)
        with tempfile.TemporaryDirectory() as tmp:
            status = os.path.join(tmp, "scan_status.json")
            with patch("engine.scanner.SCAN_STATUS_PATH", status), \
                 patch.object(AtscScanner, "_work_tuner_ready", return_value=True), \
                 patch("engine.scanner.subprocess.Popen", side_effect=OSError):
                gen = scanner.scan(quick_mode=True)
                self.assertEqual(next(gen)["status"], "starting")
                with self.assertRaises(OSError):
                    next(gen)
            with open(status, encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["status"], "idle")


if __name__ == "__main__":
    unittest.main()
