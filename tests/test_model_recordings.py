"""The Recordings tabs run the real Model.js: day headers, the row line, and the Scheduled sections."""

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
const rows = ctx.recordedRows(sorted, i.now);
const sched = ctx.scheduledRows(i.active, i.waiting, i.rules, i.now, ch => ({ "65.3": "TOONS" })[ch] || "");
process.stdout.write(JSON.stringify({
  rows: rows.map(r => r.header || (sorted[r.index].title + " | " + ctx.recordingLine(r.rec, i.now))),
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
    def _run(self, recs=(), active=(), waiting=(), rules=()):
        payload = {"recs": list(recs), "active": list(active), "waiting": list(waiting), "rules": list(rules), "now": NOW}
        env = dict(os.environ, TZ="America/New_York")
        res = subprocess.run(["node", "-e", RUNNER, MODEL, json.dumps(payload)],
                             capture_output=True, text=True, timeout=30, env=env)
        self.assertEqual(res.returncode, 0, res.stderr)
        return json.loads(res.stdout)

    def test_recorded_rows_group_by_day_newest_first(self):
        out = self._run(recs=[
            rec("M*A*S*H", NOW - 86400 - 10860, 34, ads=3),
            rec("Bugs Bunny and Friends", NOW - 8820, 8, ads=1),
            rec("Cartoon All-Stars", NOW - 1800, 0, end=None, status="recording"),
        ])
        self.assertEqual(out["rows"], [
            "Today",
            "Cartoon All-Stars | ● Recording · 30 min · 12.0 MB",
            "Bugs Bunny and Friends | 8 min · 12.0 MB · skips 1 ad break",
            "Yesterday · Fri Sep 25",
            "M*A*S*H | 34 min · 12.0 MB · skips 3 ad breaks",
        ])

    def test_an_empty_file_says_so_instead_of_a_size(self):
        out = self._run(recs=[rec("Morning", NOW - 12 * 3600 + 1800, 120, playable=False)])
        self.assertEqual(out["rows"][1], "Morning | 2 h · nothing recorded")

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
