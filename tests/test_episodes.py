"""A run of back-to-back episodes records once and splits into one file per episode."""

import json
import os
import tempfile
import unittest

from engine.dvr import read_sidecar, write_sidecar
from engine.episodes import byte_at, chain_from, grow_runs, plan_pieces, run_stop, snap_to_breaks, split_recording, split_waiting
from engine.schedule import PAD_LATE_SEC, load_schedule, save_schedule

RATE = 1880  # bytes a second, ten TS packets
START = 1_790_000_000


def _row(ident, start, dur=1800, tune="WJW-2", title="M*A*S*H", **extra):
    row = {"id": ident, "tune_name": tune, "title": title, "start_unix": start, "duration_sec": dur,
           "pad_early_sec": 60, "pad_late_sec": 180, "status": "waiting"}
    row.update(extra)
    return row


class TestChain(unittest.TestCase):
    def test_back_to_back_and_a_rerun_gap_are_one_run(self):
        items = [
            _row("a", START),
            _row("b", START + 1800, pad_early_sec=0),
            _row("d", START + 5400),
            _row("x", START + 1800, tune="WEWS"),
            _row("far", START + 5400 + 1800 + 2 * 3600),
        ]
        run = chain_from(items, items[0])
        self.assertEqual([r["id"] for r in run], ["a", "b", "d"])
        self.assertEqual(run_stop(run), START + 5400 + 1800 + 180)

    def test_byte_at_is_a_straight_line_between_notes(self):
        marks = [(0, 0), (60, 6000), (120, 18000)]
        self.assertEqual(byte_at(marks, 30), 3000)
        self.assertEqual(byte_at(marks, 90), 12000)
        self.assertEqual(byte_at(marks, 500), 18000)


class TestSplit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, end_offset, titles=("Ep A", "Ep B", "Ep C")):
        first = START + 60
        end = START + end_offset
        packets = (end - START) * RATE // 188
        data = b"".join(bytes([i % 251]) * 188 for i in range(packets))
        path = os.path.join(self.dir, "8.2-WJW_MASH_20260923_190000.ts")
        with open(path, "wb") as f:
            f.write(data)
        marks = [[START + m * 60, m * 60 * RATE] for m in range(1, (end - START) // 60)]
        write_sidecar(path, {
            "title": "M*A*S*H", "station": "WJW", "channel": "8.2", "tune_name": "WJW-2",
            "start": START, "end": end, "status": "complete", "marks": marks,
            "episodes": [
                {"title": t, "start_unix": first + i * 1800, "duration_sec": 1800, "synopsis": f"story {i}"}
                for i, t in enumerate(titles)
            ],
        })
        return path, data

    def test_three_episodes_become_three_files(self):
        path, data = self._run(60 + 5400 + PAD_LATE_SEC)
        made = split_recording(path)
        self.assertEqual(len(made), 3)
        self.assertFalse(os.path.exists(path))
        sides = [read_sidecar(p) for p in made]
        self.assertEqual([s["title"] for s in sides], ["Ep A", "Ep B", "Ep C"])
        self.assertEqual([s["synopsis"] for s in sides], ["story 0", "story 1", "story 2"])
        self.assertEqual([s["byte_rate"] for s in sides], [RATE] * 3)
        self.assertEqual([s["listed_start"] - s["start"] for s in sides], [60, 60, 60])
        spans = [(0, 2040), (1800, 3840), (3600, 5640)]
        for p, (a, b) in zip(made, spans):
            with open(p, "rb") as f:
                self.assertEqual(f.read(), data[a * RATE:b * RATE])
        self.assertEqual(split_recording(made[0]), [])

    def test_a_run_stopped_in_the_first_episode_keeps_one_file(self):
        path, data = self._run(60 + 1500)
        self.assertEqual(split_recording(path), [path])
        side = read_sidecar(path)
        self.assertEqual(side["episodes"], [])
        self.assertEqual(side["title"], "Ep A")
        self.assertEqual(side["listed_start"], START + 60)
        self.assertEqual(os.path.getsize(path), len(data))

    def test_one_episode_is_trimmed_to_a_minute_before_and_three_after(self):
        path, data = self._run(60 + 1800 + 600, titles=("Ep A",))
        self.assertEqual(split_recording(path, airings=[]), [path])
        side = read_sidecar(path)
        with open(path, "rb") as f:
            self.assertEqual(f.read(), data[:(60 + 1800 + PAD_LATE_SEC) * RATE])
        self.assertEqual((side["start"], side["end"], side["cut"]), (START, START + 60 + 1800 + PAD_LATE_SEC, True))
        self.assertEqual(split_recording(path, airings=[]), [])

    def _manual(self, seconds, title="Live Broadcast"):
        packets = seconds * RATE // 188
        data = b"".join(bytes([i % 251]) * 188 for i in range(packets))
        path = os.path.join(self.dir, "65.3-TOONS_x_20260926_200000.ts")
        with open(path, "wb") as f:
            f.write(data)
        write_sidecar(path, {
            "title": title, "station": "TOONS", "channel": "65.3", "tune_name": "TOONS",
            "start": START, "end": START + seconds, "status": "complete",
            "marks": [[START + m * 60, m * 60 * RATE] for m in range(1, seconds // 60)],
        })
        return path, data

    def _airing(self, offset, title, seconds=1800, channel="65.3"):
        return {"channel": channel, "title": title, "start": START + offset, "duration_sec": seconds}

    def test_a_recording_without_a_listing_splits_by_what_aired(self):
        path, _ = self._manual(3600 + 120)
        airings = [self._airing(0, "Bugs"), self._airing(1800, "Daffy"), self._airing(0, "Other", channel="5.1")]
        made = split_recording(path, airings=airings)
        self.assertEqual([read_sidecar(p)["title"] for p in made], ["Bugs", "Daffy"])

    def test_a_few_minutes_of_the_next_show_are_trimmed_off(self):
        path, data = self._manual(1800 + 300)
        made = split_recording(path, airings=[self._airing(0, "Bugs"), self._airing(1800, "Daffy")])
        self.assertEqual(made, [path])
        self.assertEqual(read_sidecar(path)["title"], "Bugs")
        self.assertEqual(os.path.getsize(path), (1800 + PAD_LATE_SEC) * RATE)

    def test_a_game_keeps_every_minute(self):
        path, data = self._manual(1800 + 900, title="NFL Football")
        split_recording(path, airings=[self._airing(0, "NFL Football")])
        self.assertEqual(os.path.getsize(path), len(data))
        self.assertTrue(read_sidecar(path)["cut"])

    def test_a_recording_marked_before_the_trim_is_trimmed_and_its_breaks_move(self):
        path, data = self._manual(1800 + 900)
        write_sidecar(path, dict(read_sidecar(path), ads=[[100, 130], [200, 260], [2000, 2100]]))
        self.assertEqual(split_recording(path, airings=[self._airing(180, "Bugs")]), [path])
        side = read_sidecar(path)
        self.assertEqual((side["start"], side["end"]), (START + 120, START + 180 + 1800 + PAD_LATE_SEC))
        self.assertEqual(side["ads"], [[0, 10], [80, 140], [1880, 1980]])
        self.assertEqual(side["listed_end"], START + 180 + 1800)
        self.assertEqual(split_recording(path, airings=[]), [])

    def _snappable(self, ads, title="Bugs"):
        path, data = self._manual(2100, title=title)
        write_sidecar(path, dict(read_sidecar(path), title=title, cut=True, marks=[], byte_rate=RATE, ads=ads,
                                 listed_start=START + 30, listed_end=START + 30 + 1800))
        return path, data

    def test_the_edges_snap_to_the_breaks_between_shows(self):
        path, data = self._snappable([[10, 25], [900, 960], [1850, 1880]])
        self.assertTrue(snap_to_breaks(path, airings=[]))
        side = read_sidecar(path)
        self.assertEqual((side["start"], side["end"], side["snapped"]), (START + 25, START + 1850, True))
        self.assertEqual(side["ads"], [[875, 935]])
        lo = 25 * RATE - (25 * RATE) % 188
        with open(path, "rb") as f:
            self.assertEqual(f.read(), data[lo:1850 * RATE])
        self.assertFalse(snap_to_breaks(path, airings=[]))

    def test_a_break_inside_the_show_is_not_an_edge(self):
        path, data = self._snappable([[600, 660], [1700, 1760]])
        self.assertFalse(snap_to_breaks(path, airings=[]))
        self.assertEqual(os.path.getsize(path), len(data))
        self.assertTrue(read_sidecar(path)["snapped"])

    def test_a_game_never_snaps(self):
        path, data = self._snappable([[10, 25], [1850, 1880]], title="NFL Football")
        self.assertFalse(snap_to_breaks(path, airings=[]))
        self.assertEqual(os.path.getsize(path), len(data))

    def test_a_crash_after_one_piece_resumes(self):
        path, data = self._run(60 + 5400 + PAD_LATE_SEC)
        side = read_sidecar(path)
        pieces = plan_pieces(side, len(data))
        write_sidecar(path, dict(side, split_size=len(data), episodes=[p[0] for p in pieces[:2]]))
        with open(path, "r+b") as f:
            f.truncate(pieces[1][2])
        made = split_waiting(self.dir)
        self.assertEqual(len(made), 2)
        with open(made[1], "rb") as f:
            self.assertEqual(f.read(), data[1800 * RATE:3840 * RATE])


class TestGrow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = self.tmp.name
        self.schedule = os.path.join(d, "schedule.json")
        self.active = os.path.join(d, "active.json")
        self.rules = os.path.join(d, "rules.json")
        self.file = os.path.join(d, "run.ts")
        with open(self.file, "wb") as f:
            f.write(b"\x47" * 188 * 100)

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_next_listed_episode_joins_a_running_recording(self):
        write_sidecar(self.file, {
            "start": START, "status": "recording", "planned_end": START + 60 + 1800,
            "queue_tune": "WJW-2",
            "episodes": [{"title": "M*A*S*H", "start_unix": START + 60, "duration_sec": 1800}],
        })
        with open(self.active, "w", encoding="utf-8") as f:
            json.dump([{"session_id": "s", "channel_number": "8.2", "station": "WJW", "tune_name": "WJW-2",
                        "start_time": START, "adapter_id": 1, "file_path": self.file,
                        "socket_path": os.path.join(self.tmp.name, "none.sock"), "pid": os.getpid()}], f)
        save_schedule([
            _row("next", START + 60 + 1800, pad_early_sec=0, rule_id="r", synopsis="Radar finds a lost dog in camp."),
            _row("other", START + 60 + 1800, tune="WEWS"),
        ], self.schedule)
        joined = grow_runs(now=START + 600, schedule_path=self.schedule, active_path=self.active, rules_path=self.rules)
        self.assertEqual([r["id"] for r in joined], ["next"])
        side = read_sidecar(self.file)
        self.assertEqual(len(side["episodes"]), 2)
        self.assertEqual(side["planned_end"], START + 60 + 3600 + 180)
        self.assertEqual(side["marks"], [[START + 600, 188 * 100]])
        self.assertEqual([r["id"] for r in load_schedule(self.schedule)], ["other"])


if __name__ == "__main__":
    unittest.main()
