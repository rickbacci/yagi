"""Child argv must not carry a programme title or a filename that contains one."""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

SECRET = "SECRET-SHOW-TITLE"
SHORT_TITLES = ("", "X", "Up", "24", "M*A*S*H", SECRET)


def _joined(cmd) -> str:
    return " ".join(str(part) for part in cmd)


def _assert_clean(test, cmd):
    blob = _joined(cmd)
    test.assertNotIn(SECRET, blob)
    test.assertNotIn("yagi-rec-" + SECRET, blob)
    test.assertNotIn("SECRET_SHOW", blob)


class TestRecorderArgv(unittest.TestCase):
    def test_stream_dump_and_live_copy_hide_the_title(self):
        from engine.dvr import DvrManager, read_sidecar

        fake = MagicMock()
        fake.pid = 424242
        fake.poll.return_value = None
        with tempfile.TemporaryDirectory() as tmp:
            channels = os.path.join(tmp, "channels.json")
            with open(channels, "w", encoding="utf-8") as f:
                json.dump([{"channel_number": "8.1", "station": "FOX", "tune_name": "8.1"}], f)
            active = os.path.join(tmp, "active.json")
            with patch("subprocess.Popen", return_value=fake) as popen, \
                    patch("engine.tuner.TunerManager.adapter_is_free", return_value=True), \
                    patch.object(DvrManager, "wait_until_growing", return_value=True):
                session = DvrManager.start_recording(
                    "8.1",
                    duration=60,
                    program_title=SECRET,
                    recordings_dir=tmp,
                    channels_file=channels,
                    active_path=active,
                )
            cmd = popen.call_args[0][0]
            _assert_clean(self, cmd)
            dump = next(part.split("=", 1)[1] for part in cmd if str(part).startswith("--stream-dump="))
            self.assertTrue(os.path.samefile(dump, session.file_path))
            self.assertIn(SECRET, os.path.basename(session.file_path))
            self.assertEqual(read_sidecar(session.file_path)["title"], SECRET)
            self.assertTrue(any(name.startswith(".yagi-") for name in os.listdir(tmp)))
            names = [item["name"] for item in DvrManager.list_recordings(recordings_dir=tmp)]
            self.assertEqual(names, [os.path.basename(session.file_path)])
            from engine.argv_safe import release_pid
            release_pid(session.pid)
            self.assertFalse(any(name.startswith(".yagi-") for name in os.listdir(tmp)))

        live = {"pid": 7, "adapter": 0, "file": "/cache/live.ts"}
        with tempfile.TemporaryDirectory() as tmp:
            channels = os.path.join(tmp, "channels.json")
            with open(channels, "w", encoding="utf-8") as f:
                json.dump([{"channel_number": "5.3", "station": "LAFF", "tune_name": "LAFF"}], f)
            with patch.object(DvrManager, "wait_until_growing", return_value=True), \
                    patch("engine.timeshift.Timeshift.live_source", return_value=live), \
                    patch("engine.timeshift.Timeshift.byte_at", return_value=(1880, 1000.0)), \
                    patch("engine.timeshift.Timeshift.service_id", return_value=5), \
                    patch.object(DvrManager, "_show_start", return_value=900.0), \
                    patch("engine.dvr.subprocess.Popen", return_value=fake) as popen:
                session = DvrManager.start_recording(
                    "5.3", duration=60, program_title=SECRET,
                    recordings_dir=tmp, channels_file=channels, active_path=os.path.join(tmp, "active.json"),
                )
            cmd = popen.call_args[0][0]
            _assert_clean(self, cmd)
            self.assertTrue(os.path.samefile(cmd[-3], session.file_path))
            self.assertIn(SECRET, os.path.basename(session.file_path))

    def test_every_title_length_is_hidden_with_no_fallback(self):
        from engine.argv_safe import HeldLinks
        from engine.dvr import DvrManager

        fake = MagicMock()
        fake.pid = 424242
        fake.poll.return_value = None
        for title in SHORT_TITLES:
            with tempfile.TemporaryDirectory() as tmp:
                channels = os.path.join(tmp, "channels.json")
                with open(channels, "w", encoding="utf-8") as f:
                    json.dump([{"channel_number": "8.1", "station": "FOX", "tune_name": "8.1"}], f)
                with patch("subprocess.Popen", return_value=fake) as popen, \
                        patch("engine.tuner.TunerManager.adapter_is_free", return_value=True), \
                        patch.object(DvrManager, "wait_until_growing", return_value=True):
                    session = DvrManager.start_recording(
                        "8.1", duration=60, program_title=title,
                        recordings_dir=tmp, channels_file=channels,
                        active_path=os.path.join(tmp, "active.json"),
                    )
                cmd = popen.call_args[0][0]
                base = os.path.basename(session.file_path)
                for part in cmd:
                    self.assertNotIn(base, str(part), title)
                if title and not all(c in "0123456789abcdef" for c in title):
                    self.assertNotIn(title, _joined(cmd))
                dump = next(part.split("=", 1)[1] for part in cmd if str(part).startswith("--stream-dump="))
                self.assertTrue(dump.startswith("/dev/fd/") or os.path.basename(dump).startswith(".yagi-"))
                self.assertTrue(os.path.samefile(dump, session.file_path))
                from engine.argv_safe import release_pid
                release_pid(session.pid)

        with tempfile.TemporaryDirectory() as tmp:
            titled = os.path.join(tmp, "8.1-FOX_X_20260101_000000.ts")
            with open(titled, "wb") as f:
                f.write(b"\x47" * 188)
            shield = HeldLinks()
            with patch("engine.argv_safe.os.link", side_effect=OSError("cross-device")):
                hidden = shield.hide(titled)
            self.assertTrue(hidden.startswith("/dev/fd/"))
            self.assertNotIn(os.path.basename(titled), hidden)
            self.assertNotIn("X_20260101", hidden)
            self.assertIn(shield.fds[0], shield.fds)
            shield.release()


class TestPlaybackAndToolsArgv(unittest.TestCase):
    def _recording(self, folder):
        from engine.dvr import write_sidecar

        name = f"8.1-FOX_{SECRET}_20260101_120000.ts"
        path = os.path.join(folder, name)
        with open(path, "wb") as f:
            f.write(b"\x47" * 188 * 2000)
        write_sidecar(path, {"title": SECRET, "status": "complete", "service_id": 3})
        return path

    def test_playback_ffmpeg_comskip_ffprobe_and_fuser(self):
        from engine import ads
        from engine.episodes import in_use
        from player.controller import MpvController

        with tempfile.TemporaryDirectory() as tmp:
            path = self._recording(tmp)
            from engine.paths import TIMESHIFT_DIR, ensure_private_dir
            ensure_private_dir(TIMESHIFT_DIR)
            controller = MpvController()
            fake = MagicMock(pid=1)
            fake.poll.return_value = None
            with patch.object(controller, "_reap_stale_window"), \
                    patch("player.controller.subprocess.Popen", return_value=fake) as popen, \
                    patch("player.controller.update_player_state"), \
                    patch("os.path.exists", return_value=True):
                self.assertTrue(controller.launch_file(path))
            cmd = popen.call_args[0][0]
            _assert_clean(self, cmd)
            self.assertTrue(os.path.samefile(cmd[-1], path))
            self.assertNotIn(SECRET, os.path.basename(cmd[-1]))
            controller._drop_play_link()

            calls = []

            def run(argv, **_kw):
                calls.append(list(argv))
                return __import__("subprocess").CompletedProcess(argv, 0, stdout="", stderr="")

            with patch("engine.ads.subprocess.run", side_effect=run), \
                    patch("engine.ads.shutil.disk_usage", return_value=__import__("unittest").mock.Mock(free=1024)), \
                    patch("engine.episodes.subprocess.run", side_effect=run):
                ads.ffmpeg_ads(path, {"title": SECRET})
                ads.media_seconds(path)
                ads.comskip_ads("/usr/bin/comskip", path, {"title": SECRET, "service_id": 3})
                in_use(path)
            self.assertGreaterEqual(len(calls), 4)
            for cmd in calls:
                _assert_clean(self, cmd)
