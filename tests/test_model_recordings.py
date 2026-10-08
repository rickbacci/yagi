"""The Recordings tabs run the real Model.js: shows, episodes, and the Scheduled sections."""

import json
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
MODEL = os.path.join(ROOT, "plugin", "Model.js")
NOW = 1790476200  # Sat Sep 26 2026, 10:30 PM in New York

RUNNER = r"""
const fs = require("fs");
const vm = require("vm");
const ctx = {};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], "utf8"), ctx);
const i = JSON.parse(process.argv[2]);
const sorted = ctx.sortRecordings(i.recs);
const open = i.openTitle ? ctx.showKey(i.openTitle, i.openChannel || "") : "";
const picks = ctx.recordedPicks(sorted, i.now, open);
const sched = ctx.scheduledRows(i.active, i.waiting, i.rules, i.now, ch => ({ "65.3": "TOONS" })[ch] || "");
function line(p) {
  if (p.kind === "header") return "day | " + p.title;
  if (p.kind === "show") return "show | " + p.show.title + " | " + p.line;
  if (p.kind === "live") return "live | " + p.title + " | " + p.detail;
  return "episode | " + p.title + " | " + p.detail + (p.blurb ? " | " + p.blurb : "");
}
process.stdout.write(JSON.stringify({
  picks: picks.map(line),
  sched: sched.map(r => r.kind + " | " + r.title + (r.line ? " | " + r.line : "") + (r.series ? " | series" : "")),
  count: ctx.scheduledCount(sched),
}));
"""


def rec(title, start, minutes, **extra):
    row = {"title": title, "start": start, "end": start + minutes * 60, "mtime": start + minutes * 60,
           "channel_number": "65.3", "station": "TOONS", "size_formatted": "12.0 MB", "ads": 0, "playable": True}
    row.update(extra)
    return row


@unittest.skipUnless(shutil.which("node"), "no node")
class TestRecordingsTabs(unittest.TestCase):
    def _run(self, recs=(), active=(), waiting=(), rules=(), open_title="", open_channel=""):
        payload = {"recs": list(recs), "active": list(active), "waiting": list(waiting), "rules": list(rules),
                   "now": NOW, "openTitle": open_title, "openChannel": open_channel}
        env = dict(os.environ, TZ="America/New_York")
        res = subprocess.run(["node", "-e", RUNNER, MODEL, json.dumps(payload)],
                             capture_output=True, text=True, timeout=30, env=env)
        self.assertEqual(res.returncode, 0, res.stderr)
        return json.loads(res.stdout)

    def test_recorded_lists_shows_newest_first_and_pins_what_is_recording(self):
        out = self._run(recs=[
            rec("M*A*S*H", NOW - 86400 - 10860, 34, ads=3),
            rec("Bugs Bunny and Friends", NOW - 8820, 8, ads=1),
            rec("Cartoon All-Stars", NOW - 1800, 0, end=None, status="recording"),
        ])
        self.assertEqual(out["picks"], [
            "live | Cartoon All-Stars | ● Recording · 30 min · 65.3 TOONS",
            "show | Cartoon All-Stars | 65.3 TOONS · Today 10:00 PM",
            "show | Bugs Bunny and Friends | 65.3 TOONS · Today 8:03 PM",
            "show | M*A*S*H | 65.3 TOONS · Yesterday 7:29 PM",
        ])
        for line in out["picks"]:
            self.assertNotIn("12.0 MB", line)

    def test_opening_a_show_lists_its_episodes_by_air_time(self):
        out = self._run(recs=[
            rec("M*A*S*H", NOW - 86400 - 10860, 34, ads=3),
            rec("M*A*S*H", NOW - 7200, 30, ads=2),
        ], open_title="M*A*S*H", open_channel="65.3")
        self.assertEqual(out["picks"], [
            "day | Today",
            "episode | 8:30–9:00 PM | 30 min · skips 2 ad breaks",
            "day | Yesterday",
            "episode | 7:29–8:03 PM | 34 min · skips 3 ad breaks",
        ])

    def test_same_show_on_two_channels_stays_two_shows(self):
        out = self._run(recs=[
            rec("M*A*S*H", NOW - 3600, 30, channel_number="19.2", station="MeTV"),
            rec("MASH", NOW - 1800, 30, channel_number="19.2", station="MeTV"),
            rec("M*A*S*H", NOW - 900, 30, channel_number="5.3", station="LAFF"),
        ])
        self.assertEqual(out["picks"], [
            "show | M*A*S*H | 5.3 LAFF · Today 10:15 PM",
            "show | MASH | 19.2 MeTV · 2 · Today 10:00 PM",
        ])

    def test_a_shared_blurb_is_hidden_and_a_real_one_is_kept(self):
        shared = "The same words on every airing of this cartoon block."
        out = self._run(recs=[
            rec("Bugs Bunny and Friends", NOW - 7200, 60, synopsis=shared),
            rec("Bugs Bunny and Friends", NOW - 3600, 60, synopsis=shared),
            rec("M*A*S*H", NOW - 1800, 30, synopsis="  Klinger   tries.\n"),
            rec("M*A*S*H", NOW - 900, 30, synopsis="Hawkeye writes a letter home."),
        ], open_title="M*A*S*H", open_channel="65.3")
        self.assertEqual(out["picks"], [
            "day | Today",
            "episode | 10:15–10:45 PM | 30 min | Hawkeye writes a letter home.",
            "episode | 10:00–10:30 PM | 30 min | Klinger tries.",
        ])
        bugs = self._run(recs=[
            rec("Bugs Bunny and Friends", NOW - 7200, 60, synopsis=shared),
            rec("Bugs Bunny and Friends", NOW - 3600, 60, synopsis=shared),
        ], open_title="Bugs Bunny and Friends", open_channel="65.3")
        self.assertEqual(bugs["picks"], [
            "day | Today",
            "episode | 9:30–10:30 PM | 1 h",
            "episode | 8:30–9:30 PM | 1 h",
        ])

    def test_an_empty_file_says_so_instead_of_a_size(self):
        out = self._run(recs=[rec("Morning", NOW - 12 * 3600 + 1800, 120, playable=False)],
                        open_title="Morning", open_channel="65.3")
        self.assertEqual(out["picks"], [
            "day | Today",
            "episode | 11:00 AM–1:00 PM | 2 h · nothing recorded",
        ])

    def test_scheduled_lists_recording_then_waiting_then_series(self):
        out = self._run(
            active=[{"session_id": "dvr-1", "program_title": "Cartoon All-Stars", "start_time": NOW - 1800,
                     "duration_seconds": 3600, "channel_number": "65.3", "station": "TOONS"}],
            waiting=[{"id": "WKYC-1", "title": "3News at 11P", "start_unix": NOW + 1800, "duration_sec": 1800,
                      "display_name": "3.1 WKYC"},
                     {"id": "TOONS-2", "title": "Cartoon All-Stars", "start_unix": NOW + 7 * 86400 - 1800,
                      "duration_sec": 3600, "display_name": "65.3 TOONS", "rule_id": "r1"}],
            rules=[{"id": "r1", "title": "Cartoon All-Stars", "channel": "65.3", "keep_last": 10},
                   {"id": "r2", "title": "Bugs Bunny and Friends", "channel": "65.3"}],
        )
        self.assertEqual(out["sched"], [
            "header | Upcoming",
            "active | Cartoon All-Stars | Recording until 11:00 PM · 65.3 TOONS",
            "waiting | 3News at 11P | Today 11:00–11:30 PM · 3.1 WKYC",
            "waiting | Cartoon All-Stars | Sat Oct 3 10:00–11:00 PM · 65.3 TOONS | series",
            "header | Series",
            "series | Cartoon All-Stars | 65.3 TOONS · next Sat Oct 3 10:00 PM",
            "series | Bugs Bunny and Friends | 65.3 TOONS · next not listed yet",
        ])
        self.assertEqual(out["count"], 5)


if __name__ == "__main__":
    unittest.main()
