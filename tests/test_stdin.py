"""Personal recording details can arrive as JSON on stdin, and the widget does not put them in argv."""

import json
import os
import subprocess
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
CLI_BIN = os.path.join(PROJECT_ROOT, "bin", "yagi")
WIDGET = os.path.join(PROJECT_ROOT, "plugin", "BarWidget.qml")
HUD = os.path.join(PROJECT_ROOT, "player", "scripts", "tv_hud.lua")


class TestStdinDetails(unittest.TestCase):
    def setUp(self):
        self.env = dict(os.environ)

    def _run(self, argv, payload):
        return subprocess.run(
            [sys.executable, CLI_BIN, *argv],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=self.env,
        )

    def test_series_add_stdin_keeps_the_title_out_of_argv(self):
        title = "M*A*S*H"
        argv = ["series", "add", "--stdin"]
        res = self._run(argv, {"target": "MeTV", "title": title, "channel": "19.2"})
        self.assertEqual(res.returncode, 0, res.stderr + res.stdout)
        self.assertNotIn(title, argv)
        rules = os.path.join(self.env["XDG_CONFIG_HOME"], "yagi", "record_rules.json")
        self.assertEqual(os.stat(rules).st_mode & 0o777, 0o600)
        with open(rules, encoding="utf-8") as f:
            saved = json.load(f)["rules"]
        self.assertEqual(saved[-1]["title"], title)
        self.assertEqual(saved[-1]["channel"], "19.2")

    def test_series_add_argv_still_works(self):
        res = subprocess.run(
            [sys.executable, CLI_BIN, "series", "add", "MeTV", "--title", "News", "--channel", "3.1"],
            capture_output=True,
            text=True,
            env=self.env,
        )
        self.assertEqual(res.returncode, 0, res.stderr + res.stdout)
        self.assertIn("News", res.stdout)

    def test_record_later_and_guide_search_stdin(self):
        title = "Private Show"
        argv = ["record", "later", "--stdin"]
        res = self._run(argv, {
            "target": "WEWSHD",
            "title": title,
            "duration": "30m",
            "gps": 1400000000,
            "clock": "11:00 PM",
            "display_name": "News 5",
            "channel": "5.1",
        })
        self.assertEqual(res.returncode, 0, res.stderr + res.stdout)
        self.assertNotIn(title, argv)
        self.assertIn(title, res.stdout)
        search = ["guide", "search", "--stdin"]
        found = self._run(search, {"query": "Secret Team"})
        self.assertEqual(found.returncode, 0, found.stderr + found.stdout)
        self.assertNotIn("Secret", search)
        self.assertIn("No shows match.", found.stdout)

    def test_favorite_and_hidden_stdin(self):
        fav = self._run(["favorite", "toggle", "--stdin"], {"channel": "8.1"})
        self.assertEqual(fav.returncode, 0, fav.stderr + fav.stdout)
        self.assertNotIn("8.1", ["favorite", "toggle", "--stdin"])
        hidden = self._run(["hidden", "hide", "--stdin"], {"channel": "19.1"})
        self.assertEqual(hidden.returncode, 0, hidden.stderr + hidden.stdout)
        self.assertIn("Hid 19.1", hidden.stdout)

    def test_stdin_rejects_non_json(self):
        res = subprocess.run(
            [sys.executable, CLI_BIN, "series", "add", "--stdin"],
            input="not json",
            capture_output=True,
            text=True,
            env=self.env,
        )
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("JSON", res.stdout)

    def test_widget_and_hud_keep_titles_off_the_command_line(self):
        with open(WIDGET, encoding="utf-8") as f:
            widget = f.read()
        self.assertIn('[root.binPath, "series", "add"]', widget)
        self.assertIn('[root.binPath, "record", "start"]', widget)
        self.assertNotIn('"--title"', widget)
        self.assertNotIn('"record", "start", chName', widget)
        self.assertNotIn('"series", "add", show.tune_name', widget)
        with open(HUD, encoding="utf-8") as f:
            hud = f.read()
        record = hud[hud.index('mp.add_forced_key_binding("r"'):]
        self.assertIn('"--stdin"', record)
        self.assertIn("stdin_data", record)
        self.assertNotIn('"record", "start", tostring', record)
