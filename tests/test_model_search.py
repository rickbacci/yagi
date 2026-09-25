"""Guide search runs the real Model.js: a game is found by the team in its description."""

import json
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
MODEL = os.path.join(ROOT, "plugin", "Model.js")

RUNNER = r"""
const fs = require("fs");
const vm = require("vm");
const ctx = {};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), ctx);
const input = JSON.parse(process.argv[2]);
const out = input.queries.map(q => ctx.searchGuide(input.guide, q, 600).map(h => [h.title, h.by_title]));
process.stdout.write(JSON.stringify(out));
"""

GUIDE = {
    "19.1": {"station": "WOIO", "programs": [
        {"title": "The NFL Today", "start": "12:00 PM", "end": "1:00 PM", "synopsis": "Pregame analysis and news."},
        {"title": "NFL Football", "start": "1:00 PM", "end": "4:00 PM",
         "synopsis": "Cleveland Browns at Pittsburgh Steelers. From Acrisure Stadium."},
    ]},
    "26.2": {"station": "WUEK-2", "programs": [
        {"title": "Voices of Influence", "start": "1:00 PM", "end": "2:00 PM", "synopsis": ""},
    ]},
    "43.3": {"station": "WUAB-3", "programs": [
        {"title": "Meet the Browns", "start": "2:00 PM", "end": "2:30 PM", "synopsis": "Mr. Brown causes trouble."},
        {"title": "Browns Classic", "start": "6:00 AM", "end": "6:30 AM", "duration_sec": 1800,
         "gps_start": 1_000_000_000, "synopsis": "Aired long ago."},
    ]},
}


@unittest.skipUnless(shutil.which("node"), "no node")
class TestGuideSearch(unittest.TestCase):
    def _search(self, *queries):
        res = subprocess.run(
            ["node", "-e", RUNNER, MODEL, json.dumps({"guide": GUIDE, "queries": list(queries)})],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        return json.loads(res.stdout)

    def test_team_name_finds_the_game_and_the_sitcom(self):
        browns, = self._search("browns")
        self.assertEqual(browns, [["NFL Football", False], ["Meet the Browns", True]])

    def test_games_get_extra_time_and_pregame_does_not(self):
        runner = (
            'const fs=require("fs"),vm=require("vm");const c={};vm.createContext(c);'
            'vm.runInContext(fs.readFileSync(process.argv[1],"utf8"),c);'
            'process.stdout.write(JSON.stringify(JSON.parse(process.argv[2]).map(t=>c.isGameTitle(t))))'
        )
        titles = ["NFL Football", "College Football", "The NFL Today", "Fox NFL Kickoff", "M*A*S*H", "NBA Basketball"]
        res = subprocess.run(["node", "-e", runner, MODEL, json.dumps(titles)], capture_output=True, text=True)
        self.assertEqual(json.loads(res.stdout), [True, True, False, False, False, True])

    def test_fold_title_matches_the_engine(self):
        from engine.guide import _fold_title

        runner = (
            'const fs=require("fs"),vm=require("vm");const c={};vm.createContext(c);'
            'vm.runInContext(fs.readFileSync(process.argv[1],"utf8"),c);'
            'process.stdout.write(JSON.stringify(JSON.parse(process.argv[2]).map(t=>c.foldTitle(t))))'
        )
        titles = ["M*A*S*H", "That '70s Show", "  Law & Order:  SVU ", "Café 1-2-3", "NCIS: New Orleans"]
        res = subprocess.run(["node", "-e", runner, MODEL, json.dumps(titles)], capture_output=True, text=True)
        self.assertEqual(json.loads(res.stdout), [_fold_title(t) for t in titles])

    def test_words_match_whole_words(self):
        nfl, both = self._search("nfl", "browns steelers")
        self.assertEqual([t for t, _ in nfl], ["The NFL Today", "NFL Football"])
        self.assertEqual(both, [["NFL Football", False]])


if __name__ == "__main__":
    unittest.main()
