"""The Guide grid runs the real Model.js: rows, clipping, the now block, and search inside the grid."""

import json
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
MODEL = os.path.join(ROOT, "plugin", "Model.js")
GPS = 315964800 - 18
T0 = 1790474400  # a half hour
NOW = T0 + 420

RUNNER = r"""
const fs = require("fs");
const vm = require("vm");
const ctx = {};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), ctx);
const i = JSON.parse(process.argv[2]);
const shown = i.shown === null ? null : i.shown.map(n => i.channels[n]);
const rows = ctx.gridRows(i.channels, i.guide, ctx.gridStart(i.now), i.now, i.query, shown);
process.stdout.write(JSON.stringify({
  start: ctx.gridStart(i.now),
  end: ctx.gridEnd(rows, ctx.gridStart(i.now)),
  count: ctx.gridMatchCount(rows),
  at: ctx.blockAt(rows.length ? rows[0].blocks : [], i.now + 3300),
  airing: rows.length && rows[0].blocks.length ? ctx.blockAiring(rows[0].blocks[0]) : null,
  rows: rows.map(r => ({ ch: r.channel.channel_number, outside: r.outside, blocks: r.blocks.map(b =>
    [b.title, b.x0 - ctx.gridStart(i.now), b.x1 - ctx.gridStart(i.now), b.began_before, b.on_now, b.match]) })),
}));
"""


def prog(title, offset, minutes, synopsis=""):
    return {"title": title, "gps_start": T0 + offset - GPS, "duration_sec": minutes * 60, "synopsis": synopsis}


CHANNELS = [
    {"channel_number": "3.1", "name": "WKYC", "tune_name": "WKYC-HD"},
    {"channel_number": "5.1", "name": "WEWS", "tune_name": "WEWSHD"},
    {"channel_number": "43.1", "name": "WUAB", "tune_name": "WUAB"},
]
GUIDE = {
    "3.1": {"programs": [
        prog("College Football", -9000, 210, "Cleveland State at Akron."),
        prog("3News at 11P", 3600, 30),
        prog("Saturday Night Live", 5400, 92),
    ]},
    "5.1": {"programs": [prog("News 5 at 11pm", 3600, 35), prog("Long Ago", -90000, 30)]},
    "43.1": {"programs": [prog("Meet the Browns", 0, 30, "Mr. Brown causes trouble.")]},
}


@unittest.skipUnless(shutil.which("node"), "no node")
class TestGrid(unittest.TestCase):
    def _grid(self, query="", shown=None):
        payload = {"channels": CHANNELS, "guide": GUIDE, "now": NOW, "query": query, "shown": shown}
        res = subprocess.run(["node", "-e", RUNNER, MODEL, json.dumps(payload)], capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, res.stderr)
        return json.loads(res.stdout)

    def test_blocks_are_clipped_to_the_grid_and_the_now_block_is_marked(self):
        g = self._grid()
        self.assertEqual(g["start"], T0)
        self.assertEqual(g["end"], T0 + 5400 + 92 * 60)
        first = g["rows"][0]["blocks"][0]
        self.assertEqual(first, ["College Football", 0, -9000 + 210 * 60, True, True, False])
        self.assertEqual([b[0] for b in g["rows"][1]["blocks"]], ["News 5 at 11pm"])
        self.assertEqual(g["at"], 1)

    def test_an_airing_carries_what_the_record_buttons_need(self):
        airing = self._grid()["airing"]
        self.assertEqual(airing["tune_name"], "WKYC-HD")
        self.assertEqual(airing["gps_start"], T0 - 9000 - GPS)
        self.assertTrue(airing["on_now"])

    def test_search_keeps_only_matching_channels_and_marks_the_matches(self):
        g = self._grid("browns", shown=[0, 1])
        self.assertEqual([r["ch"] for r in g["rows"]], ["43.1"])
        self.assertTrue(g["rows"][0]["outside"])
        self.assertEqual(g["count"], 1)
        self.assertTrue(g["rows"][0]["blocks"][0][5])

    def test_a_team_name_is_a_maybe_for_a_game_with_no_description(self):
        guide = dict(GUIDE, **{"8.1": {"programs": [prog("NFL Football", 0, 210), prog("MLB Baseball", 12600, 180)]}})
        chans = CHANNELS + [{"channel_number": "8.1", "name": "FOX", "tune_name": "FOX"}]
        payload = {"channels": chans, "guide": guide, "now": NOW, "query": "browns", "shown": None}
        res = subprocess.run(["node", "-e", RUNNER, MODEL, json.dumps(payload)], capture_output=True, text=True, timeout=30)
        g = json.loads(res.stdout)
        self.assertEqual([r["ch"] for r in g["rows"]], ["43.1", "8.1"])
        self.assertEqual([b[5] for b in g["rows"][1]["blocks"]], [True, False])

    def test_a_team_in_the_description_lights_the_game(self):
        g = self._grid("akron")
        self.assertEqual(g["rows"][0]["ch"], "3.1")
        self.assertEqual([b[5] for b in g["rows"][0]["blocks"]], [True, False, False])


if __name__ == "__main__":
    unittest.main()
