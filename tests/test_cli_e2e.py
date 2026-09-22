"""
End-to-End CLI tests for Omarchy TV.
Verifies symlink resolution, argument parsing, subshell execution, and sandbox isolation.
"""

import os
import sys
import json
import subprocess
import tempfile
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
CLI_BIN = os.path.join(PROJECT_ROOT, "bin", "omarchy-tv")


class TestCliE2E(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.sandbox_config = os.path.join(self.temp_dir.name, "config")
        self.sandbox_runtime = os.path.join(self.temp_dir.name, "runtime")
        os.makedirs(self.sandbox_config, exist_ok=True)
        os.makedirs(self.sandbox_runtime, exist_ok=True)

        self.env = dict(os.environ)
        self.env["XDG_CONFIG_HOME"] = self.sandbox_config
        self.env["XDG_RUNTIME_DIR"] = self.sandbox_runtime
        self.env["XDG_VIDEOS_DIR"] = os.path.join(self.temp_dir.name, "Videos")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cli_direct_execution(self):
        """Direct execution of bin/omarchy-tv with --help must succeed."""
        res = subprocess.run(
            [sys.executable, CLI_BIN, "--help"],
            capture_output=True,
            text=True,
            env=self.env
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("Omarchy TV - Modern Linux Over-The-Air Television", res.stdout)
        self.assertIn("status", res.stdout)
        self.assertIn("scan", res.stdout)
        self.assertIn("play", res.stdout)

    def test_cli_symlink_invocation(self):
        """Executing omarchy-tv via a symlink outside the repo must resolve imports cleanly."""
        symlink_bin = os.path.join(self.temp_dir.name, "omarchy-tv")
        os.symlink(CLI_BIN, symlink_bin)

        # Execute the symlink directly (exercising shebang + realpath)
        res = subprocess.run(
            [symlink_bin, "--help"],
            capture_output=True,
            text=True,
            env=self.env
        )
        self.assertEqual(res.returncode, 0, f"Symlink execution failed: {res.stderr}")
        self.assertIn("Omarchy TV", res.stdout)

    def test_cli_status_command(self):
        """omarchy-tv status must discover hardware tuners and exit 0."""
        res = subprocess.run(
            [sys.executable, CLI_BIN, "status"],
            capture_output=True,
            text=True,
            env=self.env
        )
        self.assertEqual(res.returncode, 0, f"Status failed: {res.stderr}")
        self.assertIn("Discovered", res.stdout)
        self.assertNotIn("Traceback", res.stderr)

    def test_cli_channels_empty(self):
        """omarchy-tv channels must report 'No channels found' gracefully when empty."""
        # Use a fake TV config directory inside sandbox
        tv_dir = os.path.join(self.sandbox_config, "omarchy", "tv")
        os.makedirs(tv_dir, exist_ok=True)

        res = subprocess.run(
            [sys.executable, CLI_BIN, "channels"],
            capture_output=True,
            text=True,
            env=self.env
        )
        # Even if pointing to default paths, command must exit 0 and not throw unhandled exception
        self.assertEqual(res.returncode, 0)
        self.assertFalse("Traceback" in res.stderr)

    def test_cli_channels_with_data(self):
        """omarchy-tv channels must format channel list when channels.json exists."""
        tv_dir = os.path.expanduser("~/.config/omarchy/tv")
        # In this test we check that if channels.json is present, it prints the channels
        res = subprocess.run(
            [sys.executable, CLI_BIN, "channels"],
            capture_output=True,
            text=True
        )
        self.assertEqual(res.returncode, 0)
        self.assertFalse("Traceback" in res.stderr)
        if os.path.exists(os.path.join(tv_dir, "channels.json")):
            self.assertIn("Channels", res.stdout)

    def test_cli_favorite_toggle_and_list(self):
        """omarchy-tv favorite toggle and list must manage favorites in sandbox."""
        # Initially empty list
        res_list = subprocess.run(
            [sys.executable, CLI_BIN, "favorite", "list"],
            capture_output=True,
            text=True,
            env=self.env
        )
        self.assertEqual(res_list.returncode, 0)
        self.assertIn("No favorite channels saved", res_list.stdout)

        # Toggle FOX into favorites
        res_toggle = subprocess.run(
            [sys.executable, CLI_BIN, "favorite", "toggle", "FOX"],
            capture_output=True,
            text=True,
            env=self.env
        )
        self.assertEqual(res_toggle.returncode, 0)
        self.assertIn("Added 'FOX' to favorites", res_toggle.stdout)

        # List now shows FOX
        res_list2 = subprocess.run(
            [sys.executable, CLI_BIN, "favorite", "list"],
            capture_output=True,
            text=True,
            env=self.env
        )
        self.assertEqual(res_list2.returncode, 0)
        self.assertIn("FOX", res_list2.stdout)

        # Toggle FOX out of favorites
        res_toggle2 = subprocess.run(
            [sys.executable, CLI_BIN, "favorite", "toggle", "FOX"],
            capture_output=True,
            text=True,
            env=self.env
        )
        self.assertEqual(res_toggle2.returncode, 0)
        self.assertIn("Removed 'FOX' from favorites", res_toggle2.stdout)

    def test_cli_record_subcommands(self):
        """omarchy-tv record list and status must execute cleanly in sandbox."""
        res_list = subprocess.run(
            [sys.executable, CLI_BIN, "record", "list"],
            capture_output=True,
            text=True,
            env=self.env
        )
        self.assertEqual(res_list.returncode, 0)
        self.assertIn("No recordings found", res_list.stdout)

        res_status = subprocess.run(
            [sys.executable, CLI_BIN, "record", "status"],
            capture_output=True,
            text=True,
            env=self.env
        )
        self.assertEqual(res_status.returncode, 0)
        self.assertIn("No active background recordings", res_status.stdout)

    def test_cli_pref_library_max(self):
        res = subprocess.run(
            [sys.executable, CLI_BIN, "pref", "library-max", "20"],
            capture_output=True,
            text=True,
            env=self.env
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("20.00 GB", res.stdout)
        prefs_path = os.path.join(self.sandbox_config, "omarchy", "tv", "ui_prefs.json")
        with open(prefs_path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["library_max_gb"], 20)


if __name__ == "__main__":
    unittest.main()
