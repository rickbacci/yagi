"""Behavior the suite was not driving. Fakes only. No tuner and no live window."""

import json
import os
import signal
import socket
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from engine.dvr import DvrManager, DvrSession
from engine.follow_ts import TsFollower, main as follow_main, packet_is_video_keyframe
from engine.guide import remaining_record_minutes
from engine.timeshift import Timeshift
from engine.tuner import TunerAdapter, TunerManager
from player.controller import (
    MpvController,
    _detach_stdio,
    find_channel_index,
    is_favorite_channel,
    load_favorites_list,
    load_surf_prefs,
)


def _pkt(payload_start=True, afc=1, body=b""):
    pkt = bytearray(188)
    pkt[0] = 0x47
    pkt[1] = 0x40 if payload_start else 0x00
    pkt[3] = (afc & 0x3) << 4
    if afc in (2, 3):
        pkt[4] = 1
        pkt[5] = 0
        pkt[6:6 + len(body)] = body
    else:
        pkt[4:4 + len(body)] = body
    return bytes(pkt)


class TestTunerFakes(unittest.TestCase):
    def test_inspect_and_busy_never_open_the_stick(self):
        tool = MagicMock()
        tool.stdout = "Device DualHD (Frontend)\nCurrent v5 delivery system: ATSC\nATSC\n[DVBT]\n"
        tool.returncode = 0
        with patch("engine.tuner.os.path.exists", return_value=True), \
             patch("engine.tuner.subprocess.run", return_value=tool):
            tuner = TunerAdapter(7)
        self.assertEqual(tuner.name, "DualHD")
        self.assertTrue(tuner.supports_atsc)
        self.assertIn("DVBT", tuner.delivery_systems)

        missing = MagicMock()
        with patch("engine.tuner.os.path.exists", return_value=False), \
             patch("engine.tuner.subprocess.run", missing):
            quiet = TunerAdapter(8)
        missing.assert_not_called()
        self.assertTrue(quiet.is_busy)

        fuser = MagicMock(returncode=0, stdout="")
        with patch("engine.tuner.os.path.exists", return_value=True), \
             patch("engine.tuner.subprocess.run", return_value=fuser):
            self.assertTrue(TunerAdapter(7).is_busy)
        fuser.returncode = 1
        with patch("engine.tuner.os.path.exists", return_value=True), \
             patch("engine.tuner.subprocess.run", return_value=fuser):
            self.assertFalse(TunerAdapter(7).is_busy)
        with patch("engine.tuner.os.path.exists", return_value=True), \
             patch("engine.tuner.subprocess.run", side_effect=subprocess.TimeoutExpired("fuser", 1)):
            self.assertTrue(TunerAdapter(7).is_busy)
        with patch("engine.tuner.os.path.exists", return_value=True), \
             patch("engine.tuner.subprocess.run", side_effect=OSError):
            self.assertTrue(TunerAdapter(7).is_busy)
        with patch("engine.tuner.os.path.exists", return_value=True), \
             patch("engine.tuner.subprocess.run", side_effect=FileNotFoundError):
            self.assertFalse(TunerAdapter(7).is_busy)

    def test_allocation_skips_busy_and_excluded(self):
        free = MagicMock(adapter_id=0, supports_atsc=True, is_busy=False)
        busy = MagicMock(adapter_id=1, supports_atsc=True, is_busy=True)
        with patch.object(TunerManager, "list_tuners", return_value=[busy, free]):
            self.assertIs(TunerManager.get_adapter(0), free)
            self.assertIsNone(TunerManager.get_adapter(9))
            self.assertIs(TunerManager.get_available_tuner(exclude_adapters={1}), free)
            self.assertIsNone(TunerManager.get_available_tuner(exclude_adapters={0, 1}))
        with patch("engine.tuner.os.path.exists", return_value=False):
            self.assertFalse(TunerManager.adapter_is_free(3))


class TestChannelHelpers(unittest.TestCase):
    def test_index_favorite_and_prefs(self):
        channels = [
            {"name": "Quest", "tune_name": "Quest", "channel_number": "3.4", "network": "Quest"},
            {"name": "Other", "callsign": "WXXX"},
        ]
        self.assertIsNone(find_channel_index([], "Quest"))
        self.assertEqual(find_channel_index(channels, "3.4"), 0)
        self.assertEqual(find_channel_index(channels, "wxxx"), 1)
        self.assertIsNone(find_channel_index(channels, "missing"))
        self.assertFalse(is_favorite_channel(None, ["Quest"]))
        self.assertFalse(is_favorite_channel(channels[0], []))
        self.assertTrue(is_favorite_channel(channels[0], ["quest"]))
        self.assertFalse(is_favorite_channel(channels[1], ["NBC"]))
        with tempfile.TemporaryDirectory() as tmp:
            prefs = os.path.join(tmp, "ui.json")
            favs = os.path.join(tmp, "fav.json")
            with patch("player.controller.UI_PREFS_PATH", prefs), \
                 patch("player.controller.FAVORITES_JSON_PATH", favs):
                self.assertEqual(load_surf_prefs(), {})
                self.assertEqual(load_favorites_list(), [])
                with open(prefs, "w", encoding="utf-8") as handle:
                    handle.write("{")
                with open(favs, "w", encoding="utf-8") as handle:
                    handle.write('{"nope": 1}')
                self.assertEqual(load_surf_prefs(), {})
                self.assertEqual(load_favorites_list(), [])
                with open(prefs, "w", encoding="utf-8") as handle:
                    json.dump({"channel_filter": "all"}, handle)
                with open(favs, "w", encoding="utf-8") as handle:
                    json.dump(["Quest"], handle)
                self.assertEqual(load_surf_prefs()["channel_filter"], "all")
                self.assertEqual(load_favorites_list(), ["Quest"])

    def test_detach_stdio_uses_devnull(self):
        with patch("player.controller.os.open", return_value=8) as opened, \
             patch("player.controller.os.dup2") as dup2, \
             patch("player.controller.os.close") as closed:
            _detach_stdio()
        opened.assert_called_once()
        self.assertEqual(dup2.call_count, 3)
        closed.assert_called_once_with(8)
        with patch("player.controller.os.open", side_effect=OSError):
            _detach_stdio()

    def test_reap_signals_only_the_leftover_window(self):
        killed = []

        def kill(pid, sig):
            killed.append((pid, sig))
            if sig == 0:
                raise ProcessLookupError

        with patch.object(MpvController, "is_running", return_value=False), \
             patch("player.controller._stated_player_pid", return_value=0), \
             patch("player.controller.subprocess.check_output", return_value=(
                 "4321 mpv --input-ipc-server=/no/such/sock --wayland-app-id=omarchy-tv\n"
                 "4322 mpv --input-ipc-server=/real/omarchy-tv-mpv.sock --wayland-app-id=omarchy-tv\n"
                 "99 other\n"
             )), \
             patch("player.controller.os.kill", side_effect=kill), \
             patch("player.controller.Timeshift.load_state", return_value={"pid": 7, "follow_pid": 8}), \
             patch("player.controller.os.path.exists", return_value=False):
            MpvController(socket_path="/no/such/sock")._reap_stale_window()
        self.assertIn((4321, signal.SIGTERM), killed)
        self.assertNotIn(4322, [pid for pid, _sig in killed])
        self.assertNotIn(7, [pid for pid, _sig in killed])
        self.assertNotIn(8, [pid for pid, _sig in killed])


class TestTimeshiftStop(unittest.TestCase):
    def _fast_clock(self):
        tick = {"t": 1000.0}

        def now():
            tick["t"] += 1.0
            return tick["t"]

        return now

    def test_stop_dump_quits_then_signals(self):
        with tempfile.TemporaryDirectory() as tmp:
            sock = os.path.join(tmp, "dump.sock")
            state = os.path.join(tmp, "state.json")
            got = []

            def serve():
                server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                server.bind(sock)
                server.listen(1)
                server.settimeout(2)
                conn, _ = server.accept()
                with conn:
                    got.append(conn.recv(128))
                server.close()

            threading.Thread(target=serve, daemon=True).start()
            killed = []
            with patch("engine.timeshift.TIMESHIFT_ACTIVE_PATH", state), \
                 patch("engine.timeshift.TIMESHIFT_SOCKET_PATH", sock), \
                 patch("engine.timeshift.time.sleep"), \
                 patch("engine.timeshift.time.time", side_effect=self._fast_clock()), \
                 patch.object(Timeshift, "_pid_alive", side_effect=[True, True, False]), \
                 patch("engine.timeshift.os.kill", side_effect=lambda pid, sig: killed.append(sig)):
                Timeshift._write_state({"pid": 55, "socket": sock})
                Timeshift.stop_dump()
            self.assertIn(b"quit", got[0])
            self.assertIn(signal.SIGTERM, killed)
            self.assertFalse(os.path.exists(sock))

    def test_kill_pid_escalates_and_reaps(self):
        killed = []
        with patch("engine.timeshift.time.sleep"), \
             patch("engine.timeshift.time.time", side_effect=self._fast_clock()), \
             patch.object(Timeshift, "_pid_alive", return_value=True), \
             patch("engine.timeshift.os.kill", side_effect=lambda pid, sig: killed.append((pid, sig))), \
             patch("engine.timeshift.os.waitpid", side_effect=ChildProcessError):
            Timeshift._kill_pid(0)
            Timeshift._kill_pid(44)
        self.assertIn((44, signal.SIGTERM), killed)
        self.assertIn((44, signal.SIGKILL), killed)

    def test_reap_orphan_dumps_and_follow_pos(self):
        with tempfile.TemporaryDirectory() as tmp:
            sock = os.path.join(tmp, "follow.sock")
            state = os.path.join(tmp, "state.json")
            with patch("engine.timeshift.TIMESHIFT_ACTIVE_PATH", state):
                Timeshift._write_state({"follow_socket": sock})

                def serve():
                    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    server.bind(sock)
                    server.listen(1)
                    server.settimeout(2)
                    conn, _ = server.accept()
                    with conn:
                        conn.recv(16)
                        conn.sendall(b"1880")
                    server.close()

                threading.Thread(target=serve, daemon=True).start()
                self.assertEqual(Timeshift.follow_pos(), 1880)
            with patch("engine.timeshift.subprocess.check_output", return_value="12 mpv --stream-dump=/x omarchy/tv/timeshift/live.ts\nbad\n1 mpv --stream-dump=/x omarchy/tv/timeshift/live.ts\n"), \
                 patch.object(Timeshift, "_kill_pid") as kill:
                Timeshift._reap_orphan_dumps(keep_pid=12)
            kill.assert_not_called()
            listing = (
                "40 python3 /r/engine/tower_dump.py 0 551028615 /c/omarchy/tv/timeshift/live.ts /s /l\n"
                "41 mpv --script-opts=tv_hud-timeshift-file=/c/omarchy/tv/timeshift/live.ts fd://0\n"
                "42 mpv --stream-dump=/c/omarchy/tv/timeshift/live.ts dvb://FOX\n"
                "43 bash -c pgrep -af tower_dump.py; tail /c/omarchy/tv/timeshift/dump.log --stream-dump=\n"
                "44 python3 /r/engine/tower_dump.py 0 551028615 /other/omarchy/tv/timeshift/live.ts /s /l\n"
            )
            with patch("engine.timeshift.subprocess.check_output", return_value=listing), \
                 patch("engine.timeshift.TIMESHIFT_DIR", "/c/omarchy/tv/timeshift"), \
                 patch.object(Timeshift, "_kill_pid") as kill:
                Timeshift._reap_orphan_dumps()
            self.assertEqual([c.args[0] for c in kill.call_args_list], [40, 42])
            with patch("engine.timeshift.subprocess.check_output", side_effect=OSError):
                Timeshift._reap_orphan_dumps()
            with patch("engine.timeshift.systemd_user", return_value=True), \
                 patch("engine.timeshift.stop_unit", return_value=True) as stop, \
                 patch("engine.timeshift.subprocess.check_output") as sweep:
                Timeshift._reap_orphan_dumps()
            self.assertEqual([c.args[0] for c in stop.call_args_list], ["omarchy-tv-dump0.scope", "omarchy-tv-dump1.scope"])
            sweep.assert_not_called()

    def test_wait_frontend_free_keeps_waiting_when_fuser_fails(self):
        runs = [subprocess.TimeoutExpired("fuser", 0.4), MagicMock(returncode=1)]
        with patch("engine.timeshift.os.path.exists", return_value=True), \
             patch("engine.timeshift.time.sleep"), \
             patch("engine.timeshift.subprocess.run", side_effect=runs) as run:
            Timeshift._wait_frontend_free(timeout=1, adapter_id=0)
        self.assertEqual(run.call_count, 2)

    def test_wait_frontend_free_returns_without_fuser(self):
        with patch("engine.timeshift.os.path.exists", return_value=True), \
             patch("engine.timeshift.subprocess.run", side_effect=FileNotFoundError) as run:
            Timeshift._wait_frontend_free(timeout=1, adapter_id=0)
        self.assertEqual(run.call_count, 1)


class TestFollowPieces(unittest.TestCase):
    def test_keyframe_and_usage(self):
        self.assertFalse(packet_is_video_keyframe(b"\x47"))
        self.assertFalse(packet_is_video_keyframe(_pkt(payload_start=False)))
        self.assertFalse(packet_is_video_keyframe(_pkt(afc=2)))
        huge = bytearray(_pkt(afc=3))
        huge[4] = 200
        self.assertFalse(packet_is_video_keyframe(bytes(huge)))
        self.assertTrue(packet_is_video_keyframe(_pkt(body=b"\x00\x00\x01\xb3")))
        picture = bytearray(_pkt())
        picture[4:10] = b"\x00\x00\x01\x00\x00\x08"
        self.assertTrue(packet_is_video_keyframe(bytes(picture)))
        self.assertEqual(follow_main(["only-one"]), 2)

    def test_reopen_follows_a_replaced_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            live = os.path.join(tmp, "live.ts")
            sock = os.path.join(tmp, "f.sock")
            with open(live, "wb") as handle:
                handle.write(b"\x47" + b"\x00" * 187)
            follower = TsFollower(live, 0, sock, None)
            follower._open_file()
            self.assertIsNotNone(follower._fd)
            os.rename(live, live + ".old")
            with open(live, "wb") as handle:
                handle.write(b"\x47" * 188)
            follower._maybe_reopen()
            follower._publish_pos(force=True)
            with open(follower._pos_path, encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "0")
            follower._running = False
            if follower._fd is not None:
                os.close(follower._fd)


class TestRecordStop(unittest.TestCase):
    def test_stop_quits_the_ipc_socket(self):
        with tempfile.TemporaryDirectory() as tmp:
            sock = os.path.join(tmp, "rec.sock")
            path = os.path.join(tmp, "show.ts")
            got = []

            ready = threading.Event()

            def serve():
                server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                server.bind(sock)
                server.listen(1)
                server.settimeout(2)
                ready.set()
                conn, _ = server.accept()
                with conn:
                    got.append(conn.recv(64))
                server.close()

            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            self.assertTrue(ready.wait(1))
            session = DvrSession(
                "s1", "3.4", "Quest", "Quest", "Show", 0, 60, 1, path, sock, 0,
            )
            with patch.object(session, "is_active", return_value=False):
                session.stop(timeout=0.2)
            thread.join(1)
            self.assertIn(b"quit", got[0])


class TestGuideMinutes(unittest.TestCase):
    def test_remaining_minutes_from_a_span_and_a_clock(self):
        self.assertIsNone(remaining_record_minutes(None))
        from engine.psip import GPS_LEAP_SECONDS, GPS_UNIX_OFFSET
        start = 1 + GPS_UNIX_OFFSET - GPS_LEAP_SECONDS
        program = {"gps_start": 1, "duration_sec": 600}
        self.assertIsNone(remaining_record_minutes(program, now_unix=start + 1000))
        self.assertEqual(remaining_record_minutes(program, now_unix=start - 10), 10)
        self.assertEqual(remaining_record_minutes(program, now_unix=start + 300), 5)
        clocked = {"start": "1:00 AM", "end": "1:30 AM"}
        self.assertGreaterEqual(remaining_record_minutes(clocked, now_minutes=60) or 0, 1)


class TestMoreBranches(unittest.TestCase):
    def test_dump_command_skips_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            sock = os.path.join(tmp, "d.sock")
            state = os.path.join(tmp, "s.json")
            ready = threading.Event()

            def serve():
                server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                server.bind(sock)
                server.listen(1)
                server.settimeout(2)
                ready.set()
                conn, _ = server.accept()
                with conn:
                    conn.recv(256)
                    conn.sendall(b'{"event":"x"}\nnot-json\n{"error":"success"}\n')
                server.close()

            threading.Thread(target=serve, daemon=True).start()
            self.assertTrue(ready.wait(1))
            with patch("engine.timeshift.TIMESHIFT_ACTIVE_PATH", state):
                Timeshift._write_state({"socket": sock})
                self.assertEqual(Timeshift._dump_command(["quit"])["error"], "success")
                self.assertIsNone(Timeshift._dump_command(["quit"], timeout=0.2))

    def test_hold_stops_a_full_pause(self):
        with tempfile.TemporaryDirectory() as tmp:
            live = os.path.join(tmp, "live.ts")
            sock = os.path.join(tmp, "d.sock")
            state = os.path.join(tmp, "s.json")
            with open(live, "wb") as handle:
                handle.truncate(300 * 1024)
            open(sock, "wb").close()
            with patch("engine.timeshift.TIMESHIFT_FILE", live), \
                 patch("engine.timeshift.TIMESHIFT_ACTIVE_PATH", state), \
                 patch("engine.timeshift.TIMESHIFT_SOCKET_PATH", sock), \
                 patch.object(Timeshift, "pause_cap_bytes", return_value=1), \
                 patch.object(Timeshift, "_pid_alive", return_value=True), \
                 patch("engine.timeshift.os.kill") as kill:
                Timeshift._write_state({
                    "view": "delayed", "paused": True, "pid": 77,
                    "playhead_byte": 0, "socket": sock,
                })
                self.assertTrue(Timeshift.hold_dump_if_full())
            kill.assert_called()
            with patch("engine.timeshift.TIMESHIFT_FILE", live):
                with patch.object(Timeshift, "_pid_alive", return_value=False):
                    self.assertFalse(Timeshift._wait_playable(9, 0))
                with patch.object(Timeshift, "_pid_alive", return_value=True):
                    self.assertTrue(Timeshift._wait_playable(9, 0))

    def test_channels_file_slots_and_dead_session(self):
        from engine.guide import _read_channels_file, _slot_names
        self.assertEqual(_read_channels_file("/no/such"), [])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "c.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{")
            self.assertEqual(_read_channels_file(path), [])
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"channels": [{"name": "Quest"}, "nope"]}, handle)
            self.assertEqual(_read_channels_file(path)[0]["name"], "Quest")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump([{"name": "A"}, 1], handle)
            self.assertEqual(len(_read_channels_file(path)), 1)
            self.assertIn("mash", _slot_names({"title": "M*A*S*H", "aliases": ["MASH", ""]}))
            active = os.path.join(tmp, "active.json")
            sock = os.path.join(tmp, "gone.sock")
            open(sock, "wb").close()
            row = DvrSession("s", "3.4", "Q", "Q", "Show", 0, 60, 1, os.path.join(tmp, "a.ts"), sock, 0)
            with open(active, "w", encoding="utf-8") as handle:
                json.dump([row.to_dict(), "bad"], handle)
            with patch.object(DvrSession, "is_active", return_value=False):
                self.assertEqual(DvrManager.load_active_sessions(active), [])
            self.assertFalse(os.path.exists(sock))

    def test_reopen_when_the_file_is_gone_and_seek_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            live = os.path.join(tmp, "live.ts")
            follower = TsFollower(live, 0, os.path.join(tmp, "s.sock"), None)
            follower._running = False
            follower._fd = None
            follower._maybe_reopen()
            self.assertIsNone(follower._fd)
        channels = [{"tune_name": "Quest", "frequency": 1, "service_id": 2}]
        with patch("engine.enrichment.match_channel", return_value={"tune_name": "Quest", "frequency": 1, "service_id": 2}):
            self.assertEqual(find_channel_index(channels, "anything"), 0)
        with patch("engine.enrichment.match_channel", return_value={"tune_name": "Quest", "frequency": 9, "service_id": 2}):
            self.assertIsNone(find_channel_index(channels, "anything"))

    def test_follow_stop_player_command_and_budget_off(self):
        from engine.guide import epg_tuner_held
        held = MagicMock()
        held.is_active.return_value = True
        self.assertTrue(epg_tuner_held([held]))
        self.assertFalse(epg_tuner_held([]))
        with tempfile.TemporaryDirectory() as lib:
            self.assertEqual(DvrManager.enforce_library_budget(
                recordings_dir=lib,
                prefs={"library_max_gb": "off"},
                active_path=os.path.join(lib, "active.json"),
                rules_path=os.path.join(lib, "rules.json"),
            ), [])
        with tempfile.TemporaryDirectory() as tmp:
            live = os.path.join(tmp, "live.ts")
            sock = os.path.join(tmp, "f.sock")
            state = os.path.join(tmp, "s.json")
            follower = TsFollower(live, 0, sock, None)
            follower._pos_path = os.path.join(tmp, "missing", "pos")
            follower._publish_pos(force=True)
            follower._running = False
            follower._handle_ctl("REOPEN")
            open(sock, "wb").close()
            with patch("engine.timeshift.TIMESHIFT_ACTIVE_PATH", state), \
                 patch("engine.timeshift.FOLLOW_SOCKET_PATH", sock), \
                 patch.object(Timeshift, "_pid_alive", return_value=False):
                Timeshift._write_state({"follow_pid": 0, "follow_socket": sock})
                Timeshift.stop_follow()
                self.assertFalse(os.path.exists(sock))
                Timeshift._write_state({"follow_socket": sock})
                self.assertFalse(Timeshift.send_follow_cmd("PAUSE"))
            player = MpvController(socket_path=os.path.join(tmp, "m.sock"))
            with patch("player.controller.is_allowed_playback_path", return_value=True), \
                 patch("player.controller.os.path.isfile", return_value=True), \
                 patch("player.controller.os.path.getsize", return_value=10), \
                 patch("player.controller.MIN_PLAYABLE_BYTES", 100):
                self.assertFalse(player.play_file(os.path.join(tmp, "tiny.ts")))


if __name__ == "__main__":
    unittest.main()
