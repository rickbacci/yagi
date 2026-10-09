"""Ad breaks: black, silent cuts spaced like spots. A scene fade is not a break."""

import os
import shutil
import subprocess
import tempfile
import unittest

from engine.ads import breaks_from, ffmpeg_ads, parse_detect_log, parse_edl


def _cut(t, width=0.5):
    return (t - width / 2, t + width / 2)


class TestBreaks(unittest.TestCase):
    def test_three_spots_are_a_break(self):
        cuts = [600.0, 615.2, 645.1, 660.0, 690.3]
        blacks = [_cut(t) for t in cuts]
        silences = [_cut(t, 0.8) for t in cuts]
        self.assertEqual(breaks_from(blacks, silences), [[600.0, 690.3]])

    def test_black_without_silence_is_not_a_cut(self):
        cuts = [600.0, 615.0, 645.0, 660.0]
        self.assertEqual(breaks_from([_cut(t) for t in cuts], []), [])

    def test_fades_at_odd_spacing_are_not_a_break(self):
        cuts = [100.0, 137.0, 208.0, 251.0]
        self.assertEqual(breaks_from([_cut(t) for t in cuts], [_cut(t) for t in cuts]), [])

    def test_two_breaks_stay_separate(self):
        cuts = [300.0, 330.0, 360.0, 900.0, 915.0, 945.0]
        self.assertEqual(breaks_from([_cut(t) for t in cuts], [_cut(t) for t in cuts]), [[300.0, 360.0], [900.0, 945.0]])

    def test_parse_logs(self):
        log = (
            "[blackdetect @ 0x1] black_start:40.1 black_end:40.6 black_duration:0.5\n"
            "[silencedetect @ 0x2] silence_start: 40.0\n"
            "[silencedetect @ 0x2] silence_end: 40.7 | silence_duration: 0.7\n"
        )
        self.assertEqual(parse_detect_log(log), ([(40.1, 40.6)], [(40.0, 40.7)]))
        self.assertEqual(parse_edl("12.5\t80.25\t0\nbad\n100 90 0\n"), [[12.5, 80.25]])


class TestComskipSanity(unittest.TestCase):
    def test_a_clip_marked_all_ads_falls_back_to_ffmpeg(self):
        from unittest import mock

        from engine import ads

        with mock.patch.object(ads, "comskip_path", return_value="/usr/bin/comskip"), \
                mock.patch.object(ads, "media_seconds", return_value=142.0), \
                mock.patch.object(ads, "comskip_ads", return_value=[[0.0, 141.98]]), \
                mock.patch.object(ads, "ffmpeg_ads", return_value=[[40.3, 101.8]]):
            self.assertEqual(ads.find_ads("x.ts", {}), ([[40.3, 101.8]], "ffmpeg"))
        with mock.patch.object(ads, "comskip_path", return_value="/usr/bin/comskip"), \
                mock.patch.object(ads, "media_seconds", return_value=1800.0), \
                mock.patch.object(ads, "comskip_ads", return_value=[[480.2, 587.3], [1200.0, 1350.0]]):
            self.assertEqual(ads.find_ads("x.ts", {})[1], "comskip")

    def test_halftime_is_dropped_and_the_other_breaks_stay(self):
        from unittest import mock

        from engine import ads

        with mock.patch.object(ads, "comskip_path", return_value="/usr/bin/comskip"), \
                mock.patch.object(ads, "media_seconds", return_value=4 * 3600.0), \
                mock.patch.object(ads, "comskip_ads", return_value=[[900.0, 1050.0], [5400.0, 6600.0], [7000.0, 7150.0]]):
            self.assertEqual(ads.find_ads("game.ts", {}), ([[900.0, 1050.0], [7000.0, 7150.0]], "comskip"))


class TestComskipSeesTheProgram(unittest.TestCase):
    def test_comskip_reads_a_copy_with_a_program_table_beside_the_recording(self):
        from unittest import mock

        from engine import ads

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "show.ts")
            with open(path, "wb") as f:
                f.write(b"\x47" * 188 * 100)
            os.makedirs(os.path.join(d, ".comskip-left-by-a-crash"))
            calls = []

            def run(cmd, **_kw):
                calls.append(cmd)
                if "ffmpeg" in cmd:
                    open(cmd[-1], "wb").close()
                else:
                    source = cmd[-1]
                    out = next(a.split("=", 1)[1] for a in cmd if a.startswith("--output="))
                    with open(os.path.join(out, os.path.splitext(os.path.basename(source))[0] + ".edl"), "w") as f:
                        f.write("100.5\t130.0\t0\n")
                return subprocess.CompletedProcess(cmd, 0)

            free = mock.Mock(free=100 * 1024 ** 3)
            with mock.patch.object(ads.subprocess, "run", side_effect=run), \
                    mock.patch.object(ads.shutil, "disk_usage", return_value=free):
                self.assertEqual(ads.comskip_ads("/usr/bin/comskip", path, {"service_id": 3}), [[100.5, 130.0]])
            remux, comskip = calls
            self.assertIn("-c", remux)
            self.assertEqual(remux[remux.index("-i") + 1], path)
            self.assertEqual(os.path.dirname(os.path.dirname(comskip[-1])), d)
            self.assertNotEqual(comskip[-1], path)
            self.assertEqual(os.listdir(d), ["show.ts"])

    def test_no_room_for_the_copy_reads_the_recording_itself(self):
        from unittest import mock

        from engine import ads

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "show.ts")
            with open(path, "wb") as f:
                f.write(b"\x47" * 188)
            with mock.patch.object(ads.shutil, "disk_usage", return_value=mock.Mock(free=1024)), \
                    mock.patch.object(ads.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
                self.assertEqual(ads.comskip_ads("/usr/bin/comskip", path), [])
            self.assertEqual(run.call_count, 1)
            self.assertEqual(run.call_args[0][0][-1], path)


class TestFinish(unittest.TestCase):
    def test_a_finished_recording_is_marked_once(self):
        from unittest import mock

        from engine.dvr import read_sidecar, write_sidecar
        from engine.episodes import finish_recordings, finish_waiting

        with tempfile.TemporaryDirectory() as d:
            done = os.path.join(d, "done.ts")
            live = os.path.join(d, "live.ts")
            for path, status in ((done, "complete"), (live, "recording")):
                with open(path, "wb") as f:
                    f.write(b"\x47" * 188 * 2000)
                write_sidecar(path, {"status": status})
            self.assertTrue(finish_waiting(d, 1000))
            with mock.patch("engine.ads.find_ads", return_value=([[10.0, 70.0]], "ffmpeg")) as found:
                self.assertEqual(finish_recordings(d, 1000), [done])
                self.assertEqual(found.call_count, 1)
            self.assertEqual(read_sidecar(done)["ads"], [[10.0, 70.0]])
            self.assertNotIn("ads", read_sidecar(live))
            self.assertFalse(finish_waiting(d, 1000))


@unittest.skipUnless(shutil.which("ffmpeg"), "no ffmpeg")
class TestFfmpegDetector(unittest.TestCase):
    def test_finds_a_break_in_a_broadcast_like_file(self):
        parts = [("testsrc", 440, 40), ("black", 0, 0.5), ("testsrc2", 880, 15), ("black", 0, 0.5),
                 ("testsrc2", 660, 30), ("black", 0, 0.5), ("testsrc2", 990, 15), ("black", 0, 0.5),
                 ("testsrc", 440, 40)]
        inputs = []
        for src, freq, dur in parts:
            if src == "black":
                inputs += ["-f", "lavfi", "-i", f"color=black:s=160x120:r=30:d={dur}",
                           "-f", "lavfi", "-i", f"aevalsrc=0:s=48000:d={dur}"]
            else:
                inputs += ["-f", "lavfi", "-i", f"{src}=s=160x120:r=30:d={dur}",
                           "-f", "lavfi", "-i", f"sine=f={freq}:r=48000:d={dur}"]
        n = len(parts)
        chain = "".join(f"[{2 * i}:v][{2 * i + 1}:a]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][a]"
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "show.ts")
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", *inputs,
                 "-filter_complex", chain, "-map", "[v]", "-map", "[a]",
                 "-c:v", "mpeg2video", "-q:v", "8", "-c:a", "mp2", "-output_ts_offset", "50000",
                 "-f", "mpegts", path],
                check=True, capture_output=True, timeout=120,
            )
            breaks = ffmpeg_ads(path, {})
        self.assertEqual(len(breaks), 1, breaks)
        self.assertAlmostEqual(breaks[0][0], 40.25, delta=1.0)
        self.assertAlmostEqual(breaks[0][1], 101.75, delta=1.0)


if __name__ == "__main__":
    unittest.main()
