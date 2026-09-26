"""Recording the tower live TV holds copies its dump. No second tuner."""

import json
import os
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from engine import pool
from engine.dvr import DvrManager, DvrSession, read_sidecar
from engine.live_copy import copy
from engine.paths import KEPT_DUMP_DIR, RECORDINGS_ACTIVE_PATH, TIMESHIFT_FILE, TIMESHIFT_SOCKET_PATH
from engine.timeshift import Timeshift
from engine.tower_dump import TowerDump

PACKET = b"\x47" + b"\x00" * 187
KEYFRAME = bytes([0x47, 0x40, 0x00, 0x10]) + b"\x00\x00\x01\xb3" + b"\x00" * 180


class TestCopier(unittest.TestCase):
    def _run(self, src, dest, start, **kw):
        stop = threading.Event()
        result = {}
        thread = threading.Thread(
            target=lambda: result.update(pos=copy(src, dest, start, running=lambda: not stop.is_set(), nap=0.01, **kw)),
            daemon=True,
        )
        thread.start()
        return stop, thread, result

    def _wait_size(self, path, size):
        deadline = time.time() + 2
        while time.time() < deadline and (not os.path.exists(path) or os.path.getsize(path) < size):
            time.sleep(0.01)

    def test_starts_on_a_keyframe_and_follows_through_a_rename(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dest = os.path.join(tmp, "live.ts"), os.path.join(tmp, "rec.ts")
            with open(src, "wb") as f:
                f.write(PACKET * 3 + KEYFRAME + PACKET * 2)
            stop, thread, _ = self._run(src, dest, 200)
            self._wait_size(dest, 188 * 3)
            os.rename(src, os.path.join(tmp, "kept.ts"))
            with open(os.path.join(tmp, "kept.ts"), "ab") as f:
                f.write(PACKET * 4)
            self._wait_size(dest, 188 * 7)
            stop.set()
            thread.join(2)
            with open(dest, "rb") as f:
                data = f.read()
            self.assertEqual(data[:188], KEYFRAME)
            self.assertEqual(len(data), 188 * 7)

    def test_a_shrinking_dump_ends_the_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dest = os.path.join(tmp, "live.ts"), os.path.join(tmp, "rec.ts")
            with open(src, "wb") as f:
                f.write(PACKET * 8)
            stop, thread, result = self._run(src, dest, 0)
            self._wait_size(dest, 188 * 8)
            os.truncate(src, 0)
            thread.join(2)
            self.assertFalse(thread.is_alive())
            self.assertEqual(result["pos"], 188 * 8)

    def test_a_dump_that_stops_growing_ends_the_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, dest = os.path.join(tmp, "live.ts"), os.path.join(tmp, "rec.ts")
            with open(src, "wb") as f:
                f.write(PACKET * 2)
            _, thread, _ = self._run(src, dest, 0, idle=0.1)
            thread.join(2)
            self.assertFalse(thread.is_alive())


class TestStartLiveCopy(unittest.TestCase):
    def test_the_live_tower_is_copied_from_the_show_start(self):
        live = {"pid": 4242, "adapter": 0, "file": "/cache/live.ts"}
        proc = MagicMock(pid=os.getpid())
        proc.poll.return_value = None
        with tempfile.TemporaryDirectory() as tmp:
            channels = os.path.join(tmp, "channels.json")
            with open(channels, "w") as f:
                json.dump([{"channel_number": "5.3", "station": "LAFF", "tune_name": "LAFF"}], f)
            active = os.path.join(tmp, "active.json")
            with patch.object(Timeshift, "live_source", return_value=live), \
                    patch.object(Timeshift, "byte_at", return_value=(1880, 1000.0)), \
                    patch.object(Timeshift, "service_id", return_value=5), \
                    patch.object(DvrManager, "_show_start", return_value=900.0), \
                    patch.object(DvrManager, "wait_until_growing", return_value=True), \
                    patch("engine.dvr.pool.pick_work", side_effect=AssertionError("took a tuner")), \
                    patch("engine.dvr.subprocess.Popen", return_value=proc) as popen:
                session = DvrManager.start_recording(
                    "5.3", duration=600, program_title="Home Improvement",
                    recordings_dir=tmp, channels_file=channels, active_path=active,
                )
            cmd = popen.call_args[0][0]
            self.assertTrue(cmd[-4].endswith("live_copy.py"))
            self.assertEqual(cmd[-3:], ["/cache/live.ts", session.file_path, "1880"])
            self.assertTrue(session.copies_live)
            self.assertEqual((session.adapter_id, session.socket_path, session.start_time), (0, "", 1000.0))
            side = read_sidecar(session.file_path)
            self.assertEqual((side["full_mux"], side["service_id"], side["start"]), (True, 5, 1000))
            self.assertIsNotNone(side["planned_end"])

    def test_the_show_start_maps_to_a_byte_no_later_than_live(self):
        state = {"tower_t": 1000.0}
        with patch.object(Timeshift, "live_join_byte", return_value=188 * 10000), \
                patch.object(Timeshift, "dump_bytes", return_value=188 * 10100), \
                patch.object(Timeshift, "write_rate", return_value=188 * 100.0), \
                patch.object(Timeshift, "load_state", return_value=state):
            byte, aired = Timeshift.byte_at(1010.0, 1101.0)
            self.assertEqual((byte, aired), (188 * 1000, 1010.0))
            self.assertEqual(Timeshift.byte_at(900.0, 1101.0)[0], 0)
            self.assertEqual(Timeshift.byte_at(None, 1101.0)[0], 188 * 10000)


class TestSharedDump(unittest.TestCase):
    def test_close_tv_keeps_a_dump_a_recording_copies(self):
        with patch.object(Timeshift, "stop_follow"), \
                patch.object(Timeshift, "load_state", return_value={"pid": 77}), \
                patch.object(Timeshift, "_pid_alive", return_value=True), \
                patch.object(Timeshift, "_copied_dumps", return_value={77}), \
                patch.object(Timeshift, "stop_dump") as stop, \
                patch.object(Timeshift, "_remove_files") as remove, \
                patch.object(Timeshift, "patch_state") as note:
            Timeshift.wipe()
        stop.assert_not_called()
        remove.assert_not_called()
        self.assertIs(note.call_args.kwargs["window"], False)

    def _shared(self, **extra):
        state = {"pid": 77, "freq": 479028615, "adapter_id": 0, "running": True}
        return (
            patch.object(Timeshift, "load_state", return_value=state),
            patch.object(Timeshift, "_pid_alive", return_value=True),
            patch.object(Timeshift, "_copied_dumps", return_value={77}),
        )

    def test_the_same_tower_reopens_on_the_shared_dump(self):
        a, b, c = self._shared()
        with a, b, c, patch.object(Timeshift, "_conf_freq", return_value=479028615), \
                patch.object(Timeshift, "service_id", return_value=5), \
                patch.object(Timeshift, "patch_state") as note, \
                patch.object(Timeshift, "_capture_dump") as capture:
            self.assertEqual(Timeshift.start_dump("LAFF"), TIMESHIFT_FILE)
        capture.assert_not_called()
        self.assertIs(note.call_args.kwargs["window"], True)

    def test_another_tower_with_both_tuners_busy_keeps_the_recording(self):
        a, b, c = self._shared()
        with a, b, c, patch.object(Timeshift, "_conf_freq", return_value=551028615), \
                patch("engine.pool.claims", return_value={0: "live", 1: "record"}), \
                patch.object(Timeshift, "_keep_dump_for_recordings") as keep:
            with self.assertRaises(pool.BothTunersBusy):
                Timeshift.start_dump("WJW")
        keep.assert_not_called()

    def test_another_tower_hands_the_dump_over_and_live_takes_the_free_tuner(self):
        a, b, c = self._shared()
        proc = MagicMock(pid=88)
        with a, b, c, patch.object(Timeshift, "_conf_freq", return_value=551028615), \
                patch("engine.pool.claims", return_value={0: "live"}), \
                patch.object(Timeshift, "_keep_dump_for_recordings") as keep, \
                patch.object(Timeshift, "wipe"), \
                patch.object(Timeshift, "_reap_orphan_dumps"), \
                patch.object(Timeshift, "_wait_frontend_free"), \
                patch.object(Timeshift, "_write_state"), \
                patch.object(Timeshift, "service_id", return_value=3), \
                patch.object(Timeshift, "_capture_dump", return_value=proc) as capture:
            Timeshift.start_dump("WJW")
        keep.assert_called_once()
        self.assertEqual(capture.call_args[0][1], 1)

    def test_handing_over_moves_the_file_and_marks_the_recording(self):
        Timeshift.ensure_dir()
        with open(TIMESHIFT_FILE, "wb") as f:
            f.write(PACKET * 4)
        open(TIMESHIFT_SOCKET_PATH, "w").close()
        copier = DvrSession("dvr-5.3-1", "5.3", "LAFF", "LAFF", "Show", time.time(), None, 0,
                            "/v/rec.ts", "", os.getpid(), source={"dump_pid": 77, "adapter": 0, "file": TIMESHIFT_FILE})
        DvrManager.save_active_sessions([copier])
        try:
            with patch.object(Timeshift, "patch_state") as note:
                Timeshift._keep_dump_for_recordings({"pid": 77, "adapter_id": 0})
            kept = os.path.join(KEPT_DUMP_DIR, "tower0.ts")
            self.assertTrue(os.path.isfile(kept))
            self.assertFalse(os.path.exists(TIMESHIFT_FILE))
            self.assertFalse(os.path.exists(TIMESHIFT_SOCKET_PATH))
            source = DvrManager.load_active_sessions()[0].source
            self.assertEqual((source["file"], source["kept"]), (kept, True))
            self.assertEqual((note.call_args.kwargs["pid"], note.call_args.kwargs["adapter_id"]), (0, None))
        finally:
            os.remove(RECORDINGS_ACTIVE_PATH)

    def test_a_kept_dump_goes_when_its_recording_ends(self):
        os.makedirs(KEPT_DUMP_DIR, exist_ok=True)
        kept = os.path.join(KEPT_DUMP_DIR, "tower1.ts")
        note = os.path.join(KEPT_DUMP_DIR, "tower1.json")
        open(kept, "w").close()
        with open(note, "w") as f:
            json.dump({"pid": 999999, "adapter": 1, "file": kept}, f)
        with patch.object(Timeshift, "_copied_dumps", return_value=set()), \
                patch.object(Timeshift, "load_state", return_value={}):
            Timeshift.release_unused_dumps()
        self.assertFalse(os.path.exists(kept))
        self.assertFalse(os.path.exists(note))

    def test_a_closed_tv_lets_go_once_its_recording_ends(self):
        with patch.object(Timeshift, "_copied_dumps", return_value=set()), \
                patch.object(Timeshift, "load_state", return_value={"pid": 77, "window": False}), \
                patch.object(Timeshift, "wipe") as wipe:
            Timeshift.release_unused_dumps()
        wipe.assert_called_once()

    def test_live_keeps_its_tuner_when_a_copy_shares_it(self):
        copier = MagicMock(adapter_id=0)
        copier.is_active.return_value = True
        with patch("engine.pool._read_json", return_value={}), \
                patch("engine.timeshift.Timeshift.load_state", return_value={"running": True, "pid": os.getpid(), "adapter_id": 0}), \
                patch("engine.dvr.DvrManager.load_active_sessions", return_value=[copier]):
            self.assertEqual(pool.claims(), {0: "live"})


class TestTowerDumpSocket(unittest.TestCase):
    def test_a_kept_dump_leaves_the_next_dump_socket_alone(self):
        tuner = MagicMock()
        tuner.fileno.return_value = -1
        tuner.read.return_value = b""
        tuner.snr.return_value = None
        with tempfile.TemporaryDirectory() as tmp:
            sock = os.path.join(tmp, "dump.sock")
            dump = TowerDump(tuner, os.path.join(tmp, "live.ts"), os.path.join(tmp, "dump.log"))
            thread = threading.Thread(target=dump.serve, args=(sock, 0.02), daemon=True)
            thread.start()
            deadline = time.time() + 2
            while time.time() < deadline and not os.path.exists(sock):
                time.sleep(0.01)
            os.unlink(sock)
            newer = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            newer.bind(sock)
            try:
                dump.running = False
                thread.join(2)
                self.assertTrue(os.path.exists(sock))
            finally:
                newer.close()
                dump.close()


if __name__ == "__main__":
    unittest.main()
