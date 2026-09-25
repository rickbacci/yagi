"""
Unit tests for Omarchy TV - MPV Player Controller & Channel Cycling
"""

import os
import json
import socket
import subprocess
import sys
import threading
import time
import unittest
import tempfile
from unittest.mock import patch, MagicMock

from player.controller import (
    MpvController,
    update_player_state,
    parse_dvb_path,
    is_dvb_path,
    is_follow_path,
    channel_index,
    _toggle_omarchy_fullscreen,
    OMARCHY_FULLSCREEN_LUA,
    reap_after_exit,
    spawn_reap,
)
from engine.paths import FOLLOW_FIFO_PATH
from engine.enrichment import enrich_and_sort_channels, load_station_map
from engine.timeshift import Timeshift


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
LUA_HUD = os.path.join(PROJECT_ROOT, "player", "scripts", "tv_hud.lua")
CLI_BIN = os.path.join(PROJECT_ROOT, "bin", "omarchy-tv")


_CLEVELAND = load_station_map(os.path.join(PROJECT_ROOT, "markets", "cleveland.json"))
ENRICHED_CHANNELS = enrich_and_sort_channels(
    [
        {"name": "WKYC-HD", "raw_name": "WKYC-HD", "frequency": 503028615, "service_id": 1},
        {"name": "WEWSHD", "raw_name": "WEWSHD", "frequency": 479028615, "service_id": 3},
        {"name": "FOX", "raw_name": "FOX", "frequency": 183028615, "service_id": 3},
        {"name": "COZI TV", "raw_name": "COZI TV", "frequency": 503028615, "service_id": 3},
    ],
    known=_CLEVELAND,
)


class FakeMpvIpc:
    """UNIX-socket MPV stand-in that emits an event before every command reply."""

    def __init__(self, socket_path, path_value="dvb://WKYC-HD"):
        self.socket_path = socket_path
        self.path_value = path_value
        self.time_pos = 0
        self.duration = 0
        self.commands = []
        self.loaded = []
        self._stop = threading.Event()
        self._thread = None
        self._server = None

    def start(self):
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(self.socket_path)
        self._server.listen(8)
        self._server.settimeout(0.2)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._server:
            try:
                self._server.close()
            except OSError:
                pass
        if self._thread:
            self._thread.join(timeout=1.5)
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass

    def _run(self):
        while not self._stop.is_set():
            try:
                conn, _ = self._server.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                conn.settimeout(1.0)
                try:
                    conn.sendall(b'{"event":"start-file"}\n')
                    data = b""
                    while b"\n" not in data:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        data += chunk
                    if not data:
                        continue
                    msg = json.loads(data.split(b"\n", 1)[0].decode("utf-8"))
                    self.commands.append(msg)
                    cmd = msg.get("command") or []
                    reply = {"error": "success", "request_id": msg.get("request_id")}
                    if cmd[:2] == ["get_property", "path"]:
                        reply["data"] = self.path_value
                    elif cmd[:2] == ["get_property", "pid"]:
                        reply["data"] = 4242
                    elif cmd[:2] == ["get_property", "playback-time"]:
                        reply["data"] = None
                        reply["error"] = "property unavailable"
                    elif cmd[:2] == ["get_property", "time-pos"]:
                        reply["data"] = self.time_pos
                    elif cmd[:2] == ["get_property", "duration"]:
                        reply["data"] = self.duration
                    elif cmd[:2] == ["get_property", "percent-pos"]:
                        reply["data"] = getattr(self, "percent_pos", 0)
                    elif cmd[:2] == ["get_property", "stream-pos"]:
                        reply["data"] = getattr(self, "stream_pos", 0)
                    elif cmd[:2] == ["get_property", "file-size"]:
                        reply["data"] = getattr(self, "file_size", 0)
                    elif cmd and cmd[0] == "loadfile":
                        self.loaded.append(cmd[1])
                        self.path_value = cmd[1]
                    elif cmd and cmd[0] == "quit":
                        conn.sendall((json.dumps(reply) + "\n").encode("utf-8"))
                        try:
                            os.unlink(self.socket_path)
                        except OSError:
                            pass
                        continue
                    conn.sendall((json.dumps(reply) + "\n").encode("utf-8"))
                except Exception:
                    pass


class TestPathAndIndexHelpers(unittest.TestCase):
    def test_parse_dvb_path_variants(self):
        self.assertEqual(parse_dvb_path("dvb://WKYC-HD"), "WKYC-HD")
        self.assertEqual(parse_dvb_path("dvb://COZI%20TV"), "COZI TV")
        self.assertEqual(parse_dvb_path("WKYC-HD"), "WKYC-HD")
        self.assertIsNone(parse_dvb_path(""))
        self.assertIsNone(parse_dvb_path(None))
        self.assertTrue(is_dvb_path("dvb://WKYC-HD"))
        self.assertFalse(is_dvb_path("/home/richardb/Videos/TV/show.ts"))
        self.assertTrue(is_follow_path("-"))
        self.assertTrue(is_follow_path("fd://0"))
        self.assertTrue(is_follow_path(FOLLOW_FIFO_PATH))
        self.assertFalse(is_follow_path("dvb://WKYC-HD"))

    def test_channel_index_uses_enriched_fields(self):
        numbers = [c["channel_number"] for c in ENRICHED_CHANNELS]
        self.assertEqual(numbers, ["3.1", "3.3", "5.1", "8.1"])
        self.assertEqual(channel_index(ENRICHED_CHANNELS, "WKYC-HD"), 0)
        self.assertEqual(channel_index(ENRICHED_CHANNELS, "3.1"), 0)
        self.assertEqual(channel_index(ENRICHED_CHANNELS, "NBC"), 0)
        self.assertEqual(channel_index(ENRICHED_CHANNELS, "COZI TV"), 1)
        self.assertEqual(channel_index(ENRICHED_CHANNELS, "3.3"), 1)
        self.assertEqual(channel_index(ENRICHED_CHANNELS, "WEWSHD"), 2)
        self.assertEqual(channel_index(ENRICHED_CHANNELS, "5.1"), 2)
        self.assertEqual(channel_index(ENRICHED_CHANNELS, "FOX"), 3)


class TestMpvPlayerController(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.state_path = os.path.join(self.tmp_dir.name, "player_state.json")
        self._state_patcher = patch("player.controller.PLAYER_STATE_PATH", self.state_path)
        self._state_patcher.start()
        self._prefs_patcher = patch(
            "player.controller.load_surf_prefs",
            return_value={"channel_filter": "all"},
        )
        self._prefs_patcher.start()
        self._favs_patcher = patch("player.controller.load_favorites_list", return_value=[])
        self._favs_patcher.start()

        self.mock_channels = [
            {"id": "53.1", "name": "53.1 Daystar", "frequency": 177028615},
            {"id": "53.2", "name": "53.2 WCDN", "frequency": 177028615},
            {"id": "7.1", "name": "7.1 WABC", "frequency": 177028615},
        ]
        self.controller = MpvController(socket_path=os.path.join(self.tmp_dir.name, "mpv.sock"))
        self.controller._load_channels = MagicMock(return_value=self.mock_channels)
        self.controller.channels = self.mock_channels
        self.lock_path = os.path.join(self.tmp_dir.name, "tune.lock")
        self._lock_patcher = patch("engine.timeshift.TUNE_LOCK_PATH", self.lock_path)
        self._lock_patcher.start()
        self._tune_status_patcher = patch(
            "engine.timeshift.TUNE_STATUS_PATH",
            os.path.join(self.tmp_dir.name, "tune_status.json"),
        )
        self._tune_status_patcher.start()
        self._reap_patcher = patch.object(MpvController, "_reap_stale_window")
        self._reap_patcher.start()

    def tearDown(self):
        self._reap_patcher.stop()
        self._tune_status_patcher.stop()
        self._lock_patcher.stop()
        self._state_patcher.stop()
        self._prefs_patcher.stop()
        self._favs_patcher.stop()
        self.tmp_dir.cleanup()

    def test_channel_load(self):
        self.assertEqual(len(self.controller.channels), 3)
        self.assertEqual(self.controller.channels[0]["name"], "53.1 Daystar")

    @patch.object(MpvController, "tune")
    @patch.object(MpvController, "get_active_channel_name")
    def test_channel_up_stateless_cycling(self, mock_active, mock_tune):
        mock_active.return_value = "53.1 Daystar"
        self.controller.channel_up()
        mock_tune.assert_called_with("53.2 WCDN")
        self.assertEqual(self.controller.current_channel_index, 1)

        mock_active.return_value = "53.2 WCDN"
        self.controller.channel_up()
        mock_tune.assert_called_with("7.1 WABC")
        self.assertEqual(self.controller.current_channel_index, 2)

        mock_active.return_value = "7.1 WABC"
        self.controller.channel_up()
        mock_tune.assert_called_with("53.1 Daystar")
        self.assertEqual(self.controller.current_channel_index, 0)

    @patch.object(MpvController, "tune")
    @patch.object(MpvController, "get_active_channel_name")
    def test_channel_down_stateless_cycling(self, mock_active, mock_tune):
        mock_active.return_value = "53.1 Daystar"
        self.controller.channel_down()
        mock_tune.assert_called_with("7.1 WABC")
        self.assertEqual(self.controller.current_channel_index, 2)

        mock_active.return_value = "7.1 WABC"
        self.controller.channel_down()
        mock_tune.assert_called_with("53.2 WCDN")
        self.assertEqual(self.controller.current_channel_index, 1)

    @patch.object(MpvController, "tune")
    @patch.object(MpvController, "get_active_channel_name")
    def test_channel_up_from_display_name_and_virtual_channel(self, mock_active, mock_tune):
        self.controller._load_channels = MagicMock(return_value=ENRICHED_CHANNELS)
        self.controller.channels = ENRICHED_CHANNELS

        mock_active.return_value = "NBC 3 (WKYC)"
        self.controller.channel_up()
        mock_tune.assert_called_with("COZI TV")

        mock_active.return_value = "5.1"
        self.controller.channel_up()
        mock_tune.assert_called_with("FOX")

        mock_active.return_value = "COZI TV"
        self.controller.channel_up()
        mock_tune.assert_called_with("WEWSHD")

    @patch.object(MpvController, "send_command")
    def test_get_active_channel_name_parsing(self, mock_send):
        mock_send.return_value = {"error": "success", "data": "dvb://53.2 WCDN"}
        active = self.controller.get_active_channel_name()
        self.assertEqual(active, "53.2 WCDN")
        mock_send.assert_called_with(["get_property", "path"])

    @patch.object(MpvController, "send_command")
    def test_get_active_channel_name_url_encoded(self, mock_send):
        mock_send.return_value = {"error": "success", "data": "dvb://COZI%20TV"}
        self.assertEqual(self.controller.get_active_channel_name(), "COZI TV")

    @patch.object(MpvController, "send_command")
    @patch("player.controller.Timeshift.current_channel", return_value="WKYC-HD")
    def test_get_active_channel_name_follow_pipe(self, _ch, mock_send):
        mock_send.return_value = {"error": "success", "data": "-"}
        self.assertEqual(self.controller.get_active_channel_name(), "WKYC-HD")

    def test_get_active_channel_name_when_offline(self):
        active = self.controller.get_active_channel_name()
        self.assertIsNone(active)

    def test_tune_shared_name_opens_that_subchannel(self):
        rows = [
            {
                "name": "KONV-LD",
                "tune_name": "KONV-LD",
                "channel_number": "28.1",
                "service_id": 1001,
                "display_name": "KONV-LD 1",
            },
            {
                "name": "KONV-LD",
                "tune_name": "KONV-LD",
                "channel_number": "28.2",
                "service_id": 1002,
                "display_name": "KONV-LD 2",
            },
        ]
        self.controller._load_channels = MagicMock(return_value=rows)
        conf = os.path.join(self.tmp_dir.name, "channels.conf")
        with open(conf, "w", encoding="utf-8") as handle:
            handle.write(
                "KONV-LD:527028615:8VSB:0:0:1001\n"
                "28.1:527028615:8VSB:0:0:1001\n"
                "KONV-LD:527028615:8VSB:0:0:1002\n"
                "28.2:527028615:8VSB:0:0:1002\n"
            )
        with patch("engine.timeshift.MPV_CHANNELS_CONF", conf), \
             patch.object(self.controller, "is_running", return_value=False), \
             patch("player.controller.Timeshift.start_dump", return_value=os.path.join(self.tmp_dir.name, "live.ts")) as dump, \
             patch.object(self.controller, "launch_file", return_value=True), \
             patch("player.controller.Timeshift.finish_tune"), \
             patch("player.controller.update_player_state"):
            self.assertTrue(self.controller.tune("28.2"))
        self.assertEqual(dump.call_args[0][0], "28.2")

    @patch("player.controller.is_timeshift_path", return_value=True)
    @patch("player.controller.Timeshift.start_follow", return_value=4242)
    @patch("player.controller.Timeshift.live_edge_byte", return_value=0)
    @patch("player.controller.Timeshift.start_dump")
    @patch.object(MpvController, "is_running", return_value=False)
    @patch("subprocess.Popen")
    @patch("os.path.exists", return_value=True)
    def test_live_launch_plays_dump_file_not_dvbin(self, mock_exists, mock_popen, mock_running, mock_dump, _edge, mock_follow, _ts_path):
        dump = os.path.join(self.tmp_dir.name, "live.ts")
        with open(dump, "wb") as f:
            f.write(b"x" * (256 * 1024))
        mock_dump.return_value = dump
        mock_popen.return_value = MagicMock(pid=9)

        with patch("player.controller._open_follow_reader", return_value=30), \
             patch("player.controller.os.close"), \
             patch("player.controller.Timeshift.patch_state"), \
             patch("player.controller.update_player_state"), \
             patch("player.controller.Timeshift.picture_open_byte", return_value=0):
            self.controller.launch(channel_name="53.1 Daystar", adapter_id=None)

        mock_dump.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        self.assertIn("--force-window=immediate", cmd)
        self.assertIn("--window-dragging=no", cmd)
        self.assertIn("--keepaspect-window=no", cmd)
        self.assertNotIn("--geometry=1280x720", cmd)
        self.assertNotIn("--idle=yes", cmd)
        self.assertFalse(any(str(arg).startswith("--dvbin-") for arg in cmd))
        self.assertEqual(cmd[-1], "fd://0")
        self.assertIn("--demuxer=lavf", cmd)
        self.assertIn("--demuxer-lavf-format=mpegts", cmd)
        joined = " ".join(str(a) for a in cmd)
        self.assertIn("--demuxer-lavf-analyzeduration=2", cmd)
        self.assertTrue(any(str(a).startswith("--demuxer-lavf-probesize=") for a in cmd))
        self.assertNotIn("scan_all_pmts=1", joined)
        mock_follow.assert_called_with(0)
        self.assertIn("--cache-pause=no", cmd)
        self.assertGreater(cmd.index("--cache=no"), cmd.index("--cache=yes"))
        self.assertIn("--demuxer-readahead-secs=3", cmd)
        self.assertIn("--demuxer-max-bytes=4194304", cmd)
        self.assertIn("--ytdl=no", cmd)
        self.assertIn("--mute=yes", cmd)
        self.assertIn("--sub-create-cc-track=yes", cmd)
        self.assertIn("--slang=eng", cmd)
        self.assertIn("--subs-fallback=yes", cmd)
        self.assertTrue(any("tv_hud-timeshift-file=" in str(arg) for arg in cmd))
        self.assertTrue(any("tv_hud-tune=" in str(arg) for arg in cmd))
        self.assertTrue(any("tv_hud-follow-sock=" in str(arg) for arg in cmd))
        self.assertNotEqual(cmd[-1], "-")

    @patch("player.controller.is_timeshift_path", return_value=True)
    @patch("player.controller.Timeshift.start_follow", return_value=None)
    @patch("player.controller.Timeshift.start_dump")
    @patch.object(MpvController, "is_running", return_value=False)
    @patch("subprocess.Popen")
    def test_live_launch_aborts_when_follow_fails(self, mock_popen, mock_running, mock_dump, _follow, _ts_path):
        dump = os.path.join(self.tmp_dir.name, "live.ts")
        with open(dump, "wb") as f:
            f.write(b"x" * (256 * 1024))
        mock_dump.return_value = dump
        with patch("player.controller.Timeshift.wipe"):
            self.assertFalse(self.controller.launch(channel_name="53.1 Daystar", adapter_id=None))
        mock_popen.assert_not_called()

    @patch("player.controller.is_timeshift_path", return_value=True)
    @patch("player.controller.Timeshift.start_follow", return_value=4242)
    @patch("player.controller.Timeshift.start_dump")
    @patch.object(MpvController, "is_running", return_value=False)
    @patch("subprocess.Popen")
    def test_live_launch_aborts_when_follower_never_writes(self, mock_popen, mock_running, mock_dump, _follow, _ts_path):
        dump = os.path.join(self.tmp_dir.name, "live.ts")
        with open(dump, "wb") as f:
            f.write(b"x" * (256 * 1024))
        mock_dump.return_value = dump
        with patch("player.controller._open_follow_reader", return_value=None), \
             patch("player.controller.Timeshift.stop_follow") as stop, \
             patch("player.controller.Timeshift.picture_open_byte", return_value=0), \
             patch("player.controller.Timeshift.wipe"):
            self.assertFalse(self.controller.launch(channel_name="53.1 Daystar", adapter_id=None))
        mock_popen.assert_not_called()
        stop.assert_called()

    def _fifo(self):
        path = os.path.join(self.tmp_dir.name, "follow.fifo")
        os.mkfifo(path, 0o600)
        return path

    def test_follow_reader_waits_for_first_bytes_then_blocks(self):
        import fcntl
        import threading
        from player.controller import _open_follow_reader
        path = self._fifo()

        def writer():
            fd = os.open(path, os.O_WRONLY)
            time.sleep(0.1)
            os.write(fd, b"G" * 188)
            time.sleep(0.2)
            os.close(fd)

        t = threading.Thread(target=writer)
        t.start()
        with patch("player.controller.Timeshift._pid_alive", return_value=True):
            fd = _open_follow_reader(path, 4242, timeout=2.0)
        try:
            self.assertIsNotNone(fd)
            self.assertFalse(fcntl.fcntl(fd, fcntl.F_GETFL) & os.O_NONBLOCK)
            self.assertEqual(os.read(fd, 188), b"G" * 188)
        finally:
            t.join()
            os.close(fd)

    def test_follow_reader_gives_up_when_the_follower_dies(self):
        from player.controller import _open_follow_reader
        path = self._fifo()
        started = time.time()
        with patch("player.controller.Timeshift._pid_alive", return_value=False):
            self.assertIsNone(_open_follow_reader(path, 4242, timeout=5.0))
        self.assertLess(time.time() - started, 1.0)

    def test_follow_reader_gives_up_on_a_hangup_without_bytes(self):
        from player.controller import _open_follow_reader
        path = self._fifo()
        import threading

        def writer():
            fd = os.open(path, os.O_WRONLY)
            os.close(fd)

        t = threading.Thread(target=writer)
        t.start()
        with patch("player.controller.Timeshift._pid_alive", return_value=True):
            self.assertIsNone(_open_follow_reader(path, 4242, timeout=2.0))
        t.join()

    def test_update_player_state_atomic(self):
        update_player_state(True, channel="53.1 Daystar", station="Daystar", pid=99)
        self.assertTrue(os.path.exists(self.state_path))
        leftovers = [name for name in os.listdir(self.tmp_dir.name) if ".tmp." in name]
        self.assertEqual(leftovers, [])
        with open(self.state_path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertTrue(data["running"])
        self.assertEqual(data["channel"], "53.1 Daystar")
        self.assertEqual(data["station"], "Daystar")
        self.assertEqual(data["pid"], 99)
        self.assertEqual(data["mode"], "live")
        self.assertEqual(data["last_live"], "53.1 Daystar")
        self.assertIsInstance(data["updated_at"], (int, float))

    def test_missing_socket_does_not_create_state_file(self):
        self.assertFalse(os.path.exists(self.state_path))
        self.assertFalse(self.controller.is_running())
        self.assertFalse(os.path.exists(self.state_path))

    def test_is_running_clears_stale_state_when_socket_missing(self):
        update_player_state(True, channel="53.1 Daystar", pid=1)
        self.assertFalse(self.controller.is_running())
        with open(self.state_path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertFalse(data["running"])

    def test_is_running_clears_when_pid_dead_and_socket_stale(self):
        sock = os.path.join(self.tmp_dir.name, "stale.sock")
        with open(sock, "wb") as f:
            f.write(b"")
        self.controller.socket_path = sock
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead_pid = dead.pid
        dead.wait()
        update_player_state(True, channel="53.1 Daystar", pid=dead_pid)
        with patch.object(self.controller, "send_command", return_value=None):
            self.assertFalse(self.controller.is_running())
        self.assertFalse(os.path.exists(sock))
        with open(self.state_path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertFalse(data["running"])
        self.assertEqual(data.get("channel") or "", "")

    def test_reconcile_clears_now_playing_when_player_gone(self):
        update_player_state(True, channel="WKYC-HD", pid=1)
        with patch("engine.timeshift.Timeshift.wipe") as mock_ts:
            self.assertFalse(self.controller.reconcile())
        mock_ts.assert_called_once()
        with open(self.state_path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertFalse(data["running"])
        self.assertEqual(data.get("channel") or "", "")

    def test_reconcile_skips_wipe_while_retune_lock_held(self):
        update_player_state(True, channel="WKYC-HD", pid=1)
        Timeshift.acquire_tune_lock()
        try:
            with patch("engine.timeshift.Timeshift.wipe") as mock_ts:
                self.assertTrue(self.controller.reconcile())
            mock_ts.assert_not_called()
        finally:
            Timeshift.release_tune_lock()
        with open(self.state_path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertTrue(data["running"])
        self.assertEqual(data["channel"], "WKYC-HD")

    def test_reap_after_exit_wipes_when_window_is_gone(self):
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        with patch.object(MpvController, "reconcile", return_value=False) as mock_rec:
            kept = reap_after_exit(dead.pid, pid_wait=0.3, lock_wait=0.2)
        self.assertFalse(kept)
        mock_rec.assert_called_once()

    def test_reap_after_exit_keeps_dump_while_window_lives(self):
        with patch.object(MpvController, "reconcile", return_value=False) as mock_rec:
            kept = reap_after_exit(os.getpid(), pid_wait=0.15, lock_wait=0.1)
        self.assertTrue(kept)
        mock_rec.assert_not_called()

    def test_reap_after_exit_keeps_dump_while_tune_lock_held(self):
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        Timeshift.acquire_tune_lock()
        try:
            with patch.object(MpvController, "reconcile", return_value=False) as mock_rec:
                kept = reap_after_exit(dead.pid, pid_wait=0.2, lock_wait=0.15)
            self.assertTrue(kept)
            mock_rec.assert_not_called()
        finally:
            Timeshift.release_tune_lock()

    def test_reap_after_exit_wipes_once_tune_lock_clears(self):
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        Timeshift.acquire_tune_lock()

        def release():
            time.sleep(0.12)
            Timeshift.release_tune_lock()

        threading.Thread(target=release, daemon=True).start()
        with patch.object(MpvController, "reconcile", return_value=False) as mock_rec:
            kept = reap_after_exit(dead.pid, pid_wait=0.2, lock_wait=2.0)
        self.assertFalse(kept)
        mock_rec.assert_called_once()

    def test_spawn_reap_parent_returns_without_waiting(self):
        with patch("player.controller.os.fork", return_value=1) as mock_fork, \
             patch("player.controller.reap_after_exit") as mock_reap:
            spawn_reap(4321)
            spawn_reap(0)
        mock_fork.assert_called_once()
        mock_reap.assert_not_called()

    def test_spawn_reap_grandchild_detaches_then_reaps(self):
        with patch("player.controller.os.fork", side_effect=[0, 0]), \
             patch("player.controller.os.setsid") as mock_setsid, \
             patch("player.controller.os.chdir") as mock_chdir, \
             patch("player.controller._detach_stdio") as mock_detach, \
             patch("player.controller.os._exit") as mock_exit, \
             patch("player.controller.reap_after_exit") as mock_reap:
            spawn_reap(4321)
        mock_setsid.assert_called_once()
        mock_chdir.assert_called_once_with("/")
        mock_detach.assert_called_once()
        mock_reap.assert_called_once_with(4321)
        mock_exit.assert_called_with(0)

    @patch("player.controller.update_player_state")
    @patch.object(MpvController, "send_command", return_value=None)
    def test_is_running_does_not_clear_state_on_ipc_failure(self, mock_send, mock_update):
        with patch("os.path.exists", return_value=True):
            running = self.controller.is_running()
        self.assertFalse(running)
        mock_update.assert_not_called()


class TestMpvIpcChannelSurf(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.state_path = os.path.join(self.tmp_dir.name, "player_state.json")
        self._state_patcher = patch("player.controller.PLAYER_STATE_PATH", self.state_path)
        self._state_patcher.start()
        self._prefs_patcher = patch(
            "player.controller.load_surf_prefs",
            return_value={"channel_filter": "all"},
        )
        self._prefs_patcher.start()
        self._favs_patcher = patch("player.controller.load_favorites_list", return_value=[])
        self._favs_patcher.start()
        self.controller = MpvController(socket_path=os.path.join(self.tmp_dir.name, "mpv.sock"))
        self.controller._load_channels = MagicMock(return_value=ENRICHED_CHANNELS)
        self.controller.channels = ENRICHED_CHANNELS
        self.dump_path = os.path.join(self.tmp_dir.name, "live.ts")
        with open(self.dump_path, "wb") as f:
            f.write(b"x" * 1024)
        self._dump_patcher = patch("player.controller.Timeshift.start_dump", return_value=self.dump_path)
        self._dump_patcher.start()
        self._ch_patcher = patch("player.controller.Timeshift.current_channel", return_value="WKYC-HD")
        self._ch_patcher.start()
        self._ts_path_patcher = patch(
            "player.controller.is_timeshift_path",
            side_effect=lambda p: bool(p) and os.path.realpath(p) == os.path.realpath(self.dump_path),
        )
        self._ts_path_patcher.start()
        self._wipe_patcher = patch("player.controller.Timeshift.wipe")
        self._wipe_patcher.start()
        self.lock_path = os.path.join(self.tmp_dir.name, "tune.lock")
        self._lock_patcher = patch("engine.timeshift.TUNE_LOCK_PATH", self.lock_path)
        self._lock_patcher.start()
        self._tune_status_patcher = patch(
            "engine.timeshift.TUNE_STATUS_PATH",
            os.path.join(self.tmp_dir.name, "tune_status.json"),
        )
        self._tune_status_patcher.start()
        self._reap_patcher = patch.object(MpvController, "_reap_stale_window")
        self._reap_patcher.start()
        self._note_patcher = patch("player.controller.Timeshift.note_channel", return_value=False)
        self._note_patcher.start()
        self.server = FakeMpvIpc(self.controller.socket_path, path_value=self.dump_path)
        self.server.start()

    def tearDown(self):
        self.server.stop()
        self._note_patcher.stop()
        self._reap_patcher.stop()
        self._tune_status_patcher.stop()
        self._lock_patcher.stop()
        self._wipe_patcher.stop()
        self._ts_path_patcher.stop()
        self._dump_patcher.stop()
        self._ch_patcher.stop()
        self._state_patcher.stop()
        self._prefs_patcher.stop()
        self._favs_patcher.stop()
        self.tmp_dir.cleanup()

    def test_is_running_ignores_leading_event_and_unavailable_playback_time(self):
        self.assertTrue(self.controller.is_running())

    def test_get_active_channel_name_skips_mpv_events(self):
        self.assertEqual(self.controller.get_active_channel_name(), "WKYC-HD")

    def test_channel_up_loadfiles_same_window(self):
        with patch.object(self.controller, "launch_file", return_value=True) as mock_launch, \
             patch("player.controller.subprocess.Popen") as mock_popen, \
             patch("player.controller.Timeshift.retune_keep_window", return_value=self.dump_path) as mock_retune, \
             patch("player.controller.Timeshift.start_follow", return_value=4242), \
             patch("player.controller.Timeshift.send_follow_reopen", return_value=True), \
             patch("player.controller.Timeshift.send_follow_seek", return_value=True), \
             patch("player.controller.Timeshift.send_follow_play", return_value=True), \
             patch("player.controller.Timeshift.send_follow_catchup", return_value=True), \
             patch("player.controller.Timeshift.write_rate", return_value=1e6), \
             patch("player.controller.Timeshift.dump_bytes", return_value=256 * 1024), \
             patch("player.controller.Timeshift.patch_state"), \
             patch("player.controller.update_player_state"):
            self.controller.channel_up()
        mock_retune.assert_called()
        mock_launch.assert_not_called()
        mock_popen.assert_not_called()
        sent = [m.get("command") for m in self.server.commands]
        load = next(c for c in sent if c and c[0] == "loadfile")
        self.assertEqual(load[1], "fd://0")
        self.assertEqual(load[2], "replace")
        self.assertIn(["script-message", "tv-blank"], sent)
        self.assertFalse(
            any((c.get("command") or [None])[0] == "quit" for c in self.server.commands)
        )
        self.assertEqual(self.controller.current_channel_index, 1)

    def test_relaunch_pip_quits_then_launches(self):
        with patch.object(self.controller, "launch_file", return_value=True) as mock_launch, \
             patch("player.controller.Timeshift.acquire_tune_lock", return_value=True), \
             patch("player.controller.Timeshift.release_tune_lock"), \
             patch("player.controller.Timeshift.load_state", return_value={"path": self.dump_path}), \
             patch("player.controller.update_player_state"):
            self.assertTrue(self.controller.relaunch_pip("WEWSHD", "WEWS"))
        self.assertTrue(
            any((c.get("command") or [None])[0] == "quit" for c in self.server.commands)
        )
        mock_launch.assert_called_once()
        self.assertEqual(mock_launch.call_args.kwargs.get("channel"), "WEWSHD")

    def test_play_file_rejects_path_outside_library(self):
        with patch("player.controller.RECORDINGS_DIR", self.tmp_dir.name):
            self.assertFalse(self.controller.play_file("/etc/passwd"))

    def test_play_file_rejects_empty_stub(self):
        stub = os.path.join(self.tmp_dir.name, "empty.ts")
        with open(stub, "wb") as f:
            f.write(b"x" * 4096)
        with patch("player.controller.RECORDINGS_DIR", self.tmp_dir.name):
            with patch.object(self.controller, "launch_file") as mock_launch:
                self.assertFalse(self.controller.play_file(stub))
                mock_launch.assert_not_called()

    def test_play_file_uses_file_player_not_dvbin(self):
        rec = os.path.join(self.tmp_dir.name, "show.ts")
        with open(rec, "wb") as f:
            f.write(b"x" * (256 * 1024))
        with patch("player.controller.RECORDINGS_DIR", self.tmp_dir.name):
            with patch.object(self.controller, "is_running", return_value=False):
                with patch.object(self.controller, "launch_file", return_value=True) as mock_launch:
                    self.assertTrue(self.controller.play_file(rec))
                    mock_launch.assert_called_once_with(os.path.realpath(rec))

    @patch("subprocess.Popen")
    def test_launch_file_omits_dvbin(self, mock_popen):
        mock_popen.return_value = MagicMock(pid=1)
        rec = os.path.join(self.tmp_dir.name, "show.ts")
        with open(rec, "wb") as f:
            f.write(b"x" * (256 * 1024))
        with patch("os.path.exists", return_value=True):
            with patch("player.controller.update_player_state"):
                self.assertTrue(self.controller.launch_file(rec))
        cmd = mock_popen.call_args[0][0]
        self.assertFalse(any(str(arg).startswith("--dvbin-") for arg in cmd))
        self.assertIn("--hwdec=auto-safe", cmd)
        self.assertNotIn("--hwdec=no", cmd)
        self.assertIn("--force-seekable=yes", cmd)
        self.assertEqual(cmd[-1], rec)

    @patch("subprocess.Popen")
    def test_launch_file_opens_sidecar_service(self, mock_popen):
        mock_popen.return_value = MagicMock(pid=1)
        rec = os.path.join(self.tmp_dir.name, "tower.ts")
        with open(rec, "wb") as f:
            f.write(b"x" * (256 * 1024))
        side = os.path.splitext(rec)[0] + ".json"
        with open(side, "w", encoding="utf-8") as f:
            json.dump({"full_mux": True, "service_id": 7, "title": "MASH"}, f)
        sent = []
        with patch("os.path.exists", return_value=True), \
             patch("player.controller.update_player_state"), \
             patch.object(self.controller, "send_command", side_effect=lambda cmd: sent.append(cmd) or {"error": "success"}):
            self.assertTrue(self.controller.launch_file(rec))
        self.assertIn(["set_property", "program", 7], sent)

    def test_tune_reports_failure_when_lock_is_held(self):
        with patch("player.controller.Timeshift.acquire_tune_lock", return_value=False), \
             patch("player.controller.Timeshift.start_dump") as mock_dump:
            self.assertFalse(self.controller.tune("WKYC-HD"))
        mock_dump.assert_not_called()

    def test_tune_from_recording_relaunches_live_tuner(self):
        self.server.path_value = os.path.join(self.tmp_dir.name, "show.ts")
        with patch.object(self.controller, "launch_file", return_value=True) as mock_launch:
            self.assertTrue(self.controller.tune("WKYC-HD"))
        mock_launch.assert_called_once()
        self.assertEqual(mock_launch.call_args[0][0], self.dump_path)
        self.assertFalse(any(str(item).startswith("dvb://") for item in mock_launch.call_args[0]))

    def test_return_to_live_from_recording_retunes(self):
        rec = os.path.join(self.tmp_dir.name, "show.ts")
        self.server.path_value = rec
        update_player_state(True, channel="show.ts", station="Recording", mode="recording", last_live="WKYC-HD")
        with patch.object(self.controller, "tune", return_value=True) as mock_tune:
            self.assertTrue(self.controller.return_to_live())
        mock_tune.assert_called_once_with("WKYC-HD")

    def test_return_to_live_from_live_seeks_the_write_head(self):
        self.server.path_value = FOLLOW_FIFO_PATH
        with patch("player.controller.Timeshift.send_follow_seek", return_value=True) as mock_seek, \
             patch("player.controller.Timeshift.send_follow_play", return_value=True), \
             patch("player.controller.Timeshift.send_follow_catchup", return_value=True), \
             patch("player.controller.Timeshift.live_join_byte", return_value=376), \
             patch("player.controller.Timeshift.write_rate", return_value=2_000_000), \
             patch("player.controller.Timeshift.dump_bytes", return_value=100), \
             patch("player.controller.Timeshift.patch_state"), \
             patch("player.controller.subprocess.Popen") as mock_popen:
            self.assertTrue(self.controller.return_to_live())
        mock_seek.assert_called_with(376)
        sent = [m.get("command") for m in self.server.commands]
        self.assertFalse(any(c and c[0] == "loadfile" for c in sent))
        self.assertNotIn(["script-message", "tv-blank"], sent)
        mock_popen.assert_not_called()

    def test_return_to_live_from_timeshift_file_seeks(self):
        self.server.path_value = self.dump_path
        with patch.object(self.controller.transport, "seek_cursor", return_value=True) as mock_seek, \
             patch("player.controller.Timeshift.live_join_byte", return_value=1880):
            self.assertTrue(self.controller.return_to_live())
        mock_seek.assert_called_once()
        self.assertEqual(mock_seek.call_args[0][0], 1880)

    def test_channel_up_from_recording_uses_last_live(self):
        rec = os.path.join(self.tmp_dir.name, "show.ts")
        self.server.path_value = rec
        update_player_state(True, channel="show.ts", station="Recording", mode="recording", last_live="WKYC-HD")
        with patch.object(self.controller, "tune", return_value=True) as mock_tune:
            self.controller.channel_up()
        mock_tune.assert_called_once()
        self.assertEqual(mock_tune.call_args[0][0], ENRICHED_CHANNELS[1].get("tune_name") or ENRICHED_CHANNELS[1]["name"])

    def test_stop_releases_socket_after_quit(self):
        self.assertTrue(os.path.exists(self.controller.socket_path))
        with patch("engine.timeshift.Timeshift.wipe"):
            self.controller.stop()
        self.assertFalse(os.path.exists(self.controller.socket_path))
        self.assertFalse(self.controller.is_running())

    def test_pause_on_library_cycles_mpv(self):
        rec = os.path.join(self.tmp_dir.name, "show.ts")
        self.server.path_value = rec
        self.controller.toggle_pause()
        sent = [m.get("command") for m in self.server.commands]
        self.assertIn(["cycle", "pause"], sent)

    def test_pause_on_live_freezes_the_cursor(self):
        self.server.path_value = FOLLOW_FIFO_PATH
        with patch("player.controller.Timeshift.load_state", return_value={"view": "live", "paused": False}), \
             patch("player.controller.Timeshift.follow_pos", return_value=1880), \
             patch("player.controller.Timeshift.send_follow_pause", return_value=True) as mock_pause, \
             patch("player.controller.Timeshift.patch_state") as mock_patch, \
             patch("player.controller.subprocess.Popen") as mock_popen:
            self.controller.toggle_pause()
        sent = [m.get("command") for m in self.server.commands]
        self.assertIn(["set_property", "pause", True], sent)
        self.assertFalse(any(c and c[0] == "loadfile" for c in sent))
        mock_pause.assert_called_once()
        mock_popen.assert_not_called()
        paused_call = mock_patch.call_args.kwargs
        self.assertEqual(paused_call.get("playhead_byte"), 1880)
        self.assertTrue(paused_call.get("paused"))
        self.assertNotIn("playhead_t", paused_call)

    def test_pause_on_live_records_the_tune_lag(self):
        self.server.path_value = FOLLOW_FIFO_PATH
        with patch("player.controller.Timeshift.load_state", return_value={"view": "live", "paused": False}), \
             patch("player.controller.Timeshift.follow_pos", return_value=1880), \
             patch("player.controller.Timeshift.dump_bytes", return_value=1880 + 188 * 60000), \
             patch("player.controller.Timeshift.send_follow_pause", return_value=True), \
             patch("player.controller.Timeshift.patch_state") as mock_patch, \
             patch("player.controller.subprocess.Popen"):
            self.controller.toggle_pause()
        self.assertEqual(mock_patch.call_args.kwargs.get("live_lag"), 188 * 60000)

    def test_zap_opens_live_even_seconds_from_the_write_head(self):
        patched = []
        with patch("player.controller.Timeshift.start_follow", return_value=4242), \
             patch("player.controller.Timeshift.send_follow_reopen", return_value=True), \
             patch("player.controller.Timeshift.send_follow_seek", return_value=True), \
             patch("player.controller.Timeshift.send_follow_play", return_value=True), \
             patch("player.controller.Timeshift.send_follow_catchup", return_value=True) as catchup, \
             patch("player.controller.Timeshift.write_rate", return_value=2_000_000), \
             patch("player.controller.Timeshift.dump_bytes", return_value=20_000_000), \
             patch("player.controller.Timeshift.live_lag_bytes", return_value=0), \
             patch("player.controller.Timeshift.patch_state", side_effect=lambda **kw: patched.append(kw)), \
             patch.object(self.controller, "_load_dump"):
            self.assertTrue(self.controller.open_timeshift_dump(0, paused=False))
        catchup.assert_called()
        self.assertIn({"live_lag": 0}, patched)
        self.assertEqual(patched[-1].get("view"), "live")

    def test_play_keeps_the_paused_cursor(self):
        self.server.path_value = FOLLOW_FIFO_PATH
        with patch("player.controller.Timeshift.load_state", return_value={"view": "delayed", "paused": True, "playhead_byte": 1880}), \
             patch("player.controller.Timeshift.follow_pos", return_value=1880), \
             patch("player.controller.Timeshift.delay_sec", return_value=12.0), \
             patch("player.controller.Timeshift.write_rate", return_value=2_000_000), \
             patch("player.controller.Timeshift.send_follow_play", return_value=True), \
             patch("player.controller.Timeshift.send_follow_pace", return_value=True) as mock_pace, \
             patch("player.controller.Timeshift.patch_state") as mock_patch, \
             patch("player.controller.subprocess.Popen"):
            self.controller.toggle_pause()
        sent = [m.get("command") for m in self.server.commands]
        self.assertIn(["set_property", "pause", False], sent)
        self.assertFalse(any(c and c[0] == "loadfile" for c in sent))
        played = mock_patch.call_args.kwargs
        self.assertEqual(played.get("playhead_byte"), 1880)
        self.assertFalse(played.get("paused"))
        self.assertEqual(played.get("view"), "delayed")
        self.assertNotIn("playhead_t", played)
        mock_pace.assert_called_once_with(2_000_000)
        self.assertIn(["set_property", "speed", 1], sent)

    def test_seek_back_from_live_seeks_reader(self):
        self.server.path_value = FOLLOW_FIFO_PATH
        with patch("player.controller.Timeshift.load_state", return_value={"view": "live", "paused": False, "skip_busy": False, "playhead_byte": 0}), \
             patch("player.controller.Timeshift.follow_pos", return_value=None), \
             patch("player.controller.Timeshift.dump_bytes", return_value=10_000_000), \
             patch("player.controller.Timeshift.write_rate", return_value=2_423_750), \
             patch("player.controller.Timeshift.send_follow_seek", return_value=True) as mock_seek, \
             patch("player.controller.Timeshift.send_follow_play", return_value=True), \
             patch("player.controller.Timeshift.send_follow_pace", return_value=True), \
             patch("player.controller.Timeshift.patch_state"), \
             patch("player.controller.subprocess.Popen") as mock_popen:
            self.assertTrue(self.controller.seek(-10))
        sent = [m.get("command") for m in self.server.commands]
        self.assertFalse(any(c and c[0] == "loadfile" for c in sent))
        mock_seek.assert_called()
        mock_popen.assert_not_called()

    def test_seek_last_hop_seeks_live_not_relaunch(self):
        self.server.path_value = FOLLOW_FIFO_PATH
        with patch("player.controller.Timeshift.load_state", return_value={"view": "delayed", "paused": False, "skip_busy": False, "playhead_byte": 1000}), \
             patch("player.controller.Timeshift.follow_pos", return_value=1000), \
             patch("player.controller.Timeshift.send_follow_seek", return_value=True) as mock_seek, \
             patch("player.controller.Timeshift.send_follow_play", return_value=True), \
             patch("player.controller.Timeshift.send_follow_catchup", return_value=True), \
             patch("player.controller.Timeshift.live_join_byte", return_value=376), \
             patch("player.controller.Timeshift.write_rate", return_value=2_000_000), \
             patch("player.controller.Timeshift.dump_bytes", return_value=100), \
             patch("player.controller.Timeshift.patch_state"), \
             patch("player.controller.subprocess.Popen") as mock_popen:
            self.assertTrue(self.controller.seek(10))
        sent = [m.get("command") for m in self.server.commands]
        self.assertFalse(any(c and c[0] == "loadfile" for c in sent))
        mock_seek.assert_called_with(376)
        mock_popen.assert_not_called()

    def test_seek_back_while_delayed_uses_the_live_cursor(self):
        self.server.path_value = FOLLOW_FIFO_PATH
        with patch("player.controller.Timeshift.load_state", return_value={"view": "delayed", "paused": False, "skip_busy": False, "playhead_byte": 1880, "follow_socket": "/run/user/1000/omarchy-tv-follow.sock"}), \
             patch("player.controller.Timeshift.follow_pos", return_value=37_600_000), \
             patch("player.controller.Timeshift.delay_sec", return_value=30.0), \
             patch("player.controller.Timeshift.send_follow_seek", return_value=True) as mock_seek, \
             patch("player.controller.Timeshift.send_follow_play", return_value=True), \
             patch("player.controller.Timeshift.send_follow_pace", return_value=True), \
             patch("player.controller.Timeshift.write_rate", return_value=1_880_000), \
             patch("player.controller.Timeshift.dump_bytes", return_value=94_000_000), \
             patch("player.controller.Timeshift.patch_state"), \
             patch("player.controller.subprocess.Popen") as mock_popen:
            self.assertTrue(self.controller.seek(-10))
        mock_seek.assert_called_with(18_800_000)
        mock_popen.assert_not_called()
        sent = [m.get("command") for m in self.server.commands]
        self.assertIn(["drop-buffers"], sent)

    def test_seek_fwd_while_labeled_live_still_jumps(self):
        self.server.path_value = FOLLOW_FIFO_PATH
        pos = 188_000
        rate = 188_000
        with patch("player.controller.Timeshift.load_state", return_value={"view": "live", "paused": False, "skip_busy": False}), \
             patch("player.controller.Timeshift.follow_pos", return_value=pos), \
             patch("player.controller.Timeshift.dump_bytes", return_value=pos + int(30 * rate)), \
             patch("player.controller.Timeshift.write_rate", return_value=rate), \
             patch("player.controller.Timeshift.send_follow_seek", return_value=True) as mock_seek, \
             patch("player.controller.Timeshift.send_follow_play", return_value=True), \
             patch("player.controller.Timeshift.send_follow_pace", return_value=True), \
             patch("player.controller.Timeshift.patch_state"), \
             patch("player.controller.subprocess.Popen") as mock_popen:
            self.assertTrue(self.controller.seek(10))
        mock_seek.assert_called_with(pos + int(10 * rate))
        mock_popen.assert_not_called()
        sent = [m.get("command") for m in self.server.commands]
        self.assertFalse(any(c and c[0] == "loadfile" for c in sent))
        self.assertIn(["set_property", "speed", 1], sent)

    def test_seek_does_not_replace_a_live_reader(self):
        self.server.path_value = FOLLOW_FIFO_PATH
        pos = 188_000
        rate = 188_000
        with patch("player.controller.Timeshift.load_state", return_value={"view": "delayed", "paused": False, "skip_busy": False, "playhead_byte": pos, "follow_pid": 99}), \
             patch("player.controller.Timeshift.follow_pos", return_value=pos), \
             patch("player.controller.Timeshift.dump_bytes", return_value=pos + int(30 * rate)), \
             patch("player.controller.Timeshift.write_rate", return_value=rate), \
             patch("player.controller.Timeshift.send_follow_seek", return_value=False), \
             patch("player.controller.Timeshift._pid_alive", return_value=True), \
             patch("player.controller.Timeshift.start_follow") as mock_start, \
             patch("player.controller.Timeshift.patch_state"), \
             patch("player.controller.subprocess.Popen") as mock_popen:
            self.assertFalse(self.controller.seek(10))
        mock_start.assert_not_called()
        mock_popen.assert_not_called()

    def test_seek_asks_hud(self):
        rec = os.path.join(self.tmp_dir.name, "show.ts")
        self.server.path_value = rec
        self.assertTrue(self.controller.seek(15))
        sent = [m.get("command") for m in self.server.commands]
        self.assertIn(["script-message", "tv-seek", "15"], sent)

    def test_channel_down_wraps_to_last_station(self):
        with patch("player.controller.Timeshift.retune_keep_window", return_value=self.dump_path), \
             patch.object(self.controller, "open_timeshift_dump", return_value=True), \
             patch("player.controller.update_player_state"):
            self.controller.channel_down()
        self.assertEqual(self.controller.current_channel_index, len(ENRICHED_CHANNELS) - 1)

    def test_channel_up_from_url_encoded_cozi(self):
        self._ch_patcher.stop()
        self._ch_patcher = patch("player.controller.Timeshift.current_channel", return_value="COZI TV")
        self._ch_patcher.start()
        with patch("player.controller.Timeshift.retune_keep_window", return_value=self.dump_path) as mock_retune, \
             patch.object(self.controller, "open_timeshift_dump", return_value=True), \
             patch("player.controller.update_player_state"):
            self.controller.channel_up()
        mock_retune.assert_called()


class TestLuaChannelKeys(unittest.TestCase):
    def test_hud_keys_call_cli_not_follow_seek(self):
        with open(LUA_HUD, encoding="utf-8") as f:
            src = f.read()
        self.assertIn('mp.add_forced_key_binding("j", "tv_surf_prev_j"', src)
        self.assertIn('mp.add_forced_key_binding("k", "tv_surf_next_k"', src)
        self.assertIn("j k Channel", src)
        self.assertIn("y Save", src)
        self.assertIn('mp.add_forced_key_binding("y", "tv_keep_pause"', src)
        self.assertNotIn("surf_preview", src)
        self.assertNotIn("local function surf(", src)
        self.assertIn("ch.channel_number == tune_name", src)
        self.assertIn("j k Channel    ← → 10s", src)
        self.assertIn('"signal", "--plain"', src)
        self.assertNotIn("%d dB", src)
        self.assertIn("Weak signal", src)
        self.assertIn("signal_color", src)
        self.assertIn("Muted", src)
        self.assertNotIn("}Muted\\n", src)
        self.assertIn('mp.add_forced_key_binding("LEFT", "tv_seek_back"', src)
        self.assertIn('mp.add_forced_key_binding("RIGHT", "tv_seek_fwd"', src)
        self.assertIn('mp.add_forced_key_binding("SPACE", "tv_pause", request_pause)', src)
        self.assertIn('mp.add_forced_key_binding("l", "tv_return_live"', src)
        timer = src[src.index("mp.add_periodic_timer"):src.index("mp.add_periodic_timer") + 900]
        self.assertIn("reload_data()", timer)
        self.assertIn("banner_tune", timer)
        self.assertIn('mp.register_script_message("tv-blank"', src)
        self.assertIn("blanking", src)
        self.assertIn('cli_async({"pause"})', src)
        self.assertIn('cli_async({"seek"', src)
        self.assertIn('cli_async({"live"})', src)
        eof = src[src.index("local function on_dump_eof"):src.index('mp.register_event("playback-restart"')]
        self.assertIn('cli_async({"live"})', eof)
        self.assertNotIn('cli_async({"seek"', eof)
        self.assertNotIn("loadfile", eof)
        self.assertNotIn("drop-buffers", src)
        skip = src[src.index("local function seek_rel"):]
        skip = skip[skip.index("if is_timeshift_playback() then"):skip.index('cli_async({"seek", tostring(signed)})')]
        self.assertNotIn("loadfile", skip)
        self.assertNotIn("http://", skip)
        self.assertNotIn("send_follow_seek", src)
        self.assertNotIn("timeshift_skip", src)
        self.assertNotIn("open_dump_at", src)
        self.assertNotIn('mp.command("cycle fullscreen")', src)
        self.assertNotIn("tv_fs_key", src)
        self.assertNotIn("MBTN_LEFT_DBL", src)
        self.assertIn("Super+F", src)
        self.assertIn("function program_on_now", src)
        self.assertIn("function picture_ready", src)
        self.assertIn("cached_timeshift.mux_bps", src)
        self.assertIn("ts_delay / PAUSE_WINDOW", src)
        self.assertIn("local PAUSE_WINDOW = 3600", src)
        record_key = src[src.index('mp.add_forced_key_binding("r"'):]
        self.assertIn("recording_for_channel(ch)", record_key)
        self.assertNotIn("cached_recordings[1]", record_key)
        self.assertIn('"record", "stop"', record_key)
        self.assertIn('"record", "start"', record_key)
        self.assertIn('mp.get_opt("tune")', src)
        self.assertIn("video-params/w", src)
        self.assertIn('mp.observe_property("video-params/w"', src)
        self.assertNotIn("string.lower(p.network) == string.lower(matched_ch.network)", src)
        self.assertNotIn("Projects/personal", src)
        self.assertIn("debug.getinfo(1, \"S\")", src)
        self.assertIn("/bin/omarchy-tv", src)
        self.assertIn('args = {cli, "sync", "--reap", pid}', src)
        self.assertIn("detach = true", src)


class TestOmarchyFullscreen(unittest.TestCase):
    @patch("player.controller.subprocess.run")
    def test_unpins_tv_then_uses_omarchy_dispatcher(self, mock_run):
        tv = {
            "class": "omarchy-tv",
            "address": "0xabc",
            "pinned": True,
            "fullscreen": 0,
        }
        after = {**tv, "pinned": False, "fullscreen": 2}

        def fake_run(cmd, capture_output=True, text=True):
            m = MagicMock()
            m.returncode = 0
            m.stderr = ""
            if cmd[:3] == ["hyprctl", "activewindow", "-j"]:
                m.stdout = json.dumps(tv)
            elif cmd[:3] == ["hyprctl", "clients", "-j"]:
                m.stdout = json.dumps([after])
            else:
                m.stdout = "ok"
            return m

        mock_run.side_effect = fake_run
        _toggle_omarchy_fullscreen(target_tv=True)
        dispatched = [
            call.args[0][2]
            for call in mock_run.call_args_list
            if call.args[0][:2] == ["hyprctl", "dispatch"]
        ]
        self.assertEqual(
            dispatched[0],
            'hl.dsp.window.pin({ window = "address:0xabc" })',
        )
        self.assertEqual(
            dispatched[1],
            'hl.dsp.window.fullscreen({ mode = "fullscreen", window = "address:0xabc" })',
        )
        self.assertEqual(len(dispatched), 2)

    @patch("player.controller.subprocess.run")
    def test_other_windows_keep_stock_omarchy_fullscreen(self, mock_run):
        def fake_run(cmd, capture_output=True, text=True):
            m = MagicMock()
            m.returncode = 0
            m.stderr = ""
            if cmd[:3] == ["hyprctl", "activewindow", "-j"]:
                m.stdout = json.dumps({"class": "kitty", "pinned": False, "fullscreen": 0})
            else:
                m.stdout = "ok"
            return m

        mock_run.side_effect = fake_run
        _toggle_omarchy_fullscreen()
        dispatched = [
            call.args[0][2]
            for call in mock_run.call_args_list
            if call.args[0][:2] == ["hyprctl", "dispatch"]
        ]
        self.assertEqual(dispatched, [OMARCHY_FULLSCREEN_LUA])


class TestCliNextPrev(unittest.TestCase):
    def test_help_lists_next_and_prev(self):
        import subprocess
        import sys
        res = subprocess.run(
            [sys.executable, CLI_BIN, "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("next", res.stdout)
        self.assertIn("prev", res.stdout)
        self.assertIn("live", res.stdout)
        self.assertIn("fullscreen", res.stdout)
        self.assertIn("sync", res.stdout)


class TestPluginSessionCards(unittest.TestCase):
    def test_watch_and_record_are_separate_cards(self):
        qml = os.path.join(PROJECT_ROOT, "plugin", "BarWidget.qml")
        with open(qml, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("model: root.activeRecordings", src)
        self.assertIn("text: \"Close\"", src)
        self.assertIn("text: \"Save\"", src)
        self.assertIn("visible: root.isLiveSession && !root.pauseKept", src)
        self.assertIn("root.pauseKept = true", src)
        self.assertIn("text: \"Stop\"", src)
        self.assertNotIn("text: \"Pause\"", src)
        self.assertIn("readonly property bool showChannelBrowser: !root.guideStripOpen", src)
        self.assertNotIn("Hide the channel list", src)
        self.assertIn("id: guideUpdateCard", src)
        self.assertIn("visible: root.guideRefreshing", src)
        self.assertIn("\"Updating the Guide\"", src)
        self.assertIn("property bool guideStripOpen", src)
        self.assertIn("id: guideStripCol", src)
        self.assertIn("guideShowRows", src)
        self.assertIn("Record all", src)
        self.assertIn('"guide", "shows"', src)
        self.assertNotIn("Nothing listed in these hours.", src)
        self.assertIn("root.guideStripOpen", src)
        self.assertIn("schedule.json", src)
        self.assertIn("text: \"Waiting to record\"", src)
        self.assertIn("record\", \"later\"", src)
        self.assertNotIn("record\", \"due\"", src)
        self.assertIn("status === \"missed\"", src)
        self.assertIn("function listedKey", src)
        self.assertIn("root.listedKey(chItem.modelData)", src)
        self.assertNotIn("root.liveSnr", src)
        self.assertIn("root.tuneSnr", src)
        self.assertNotIn("\"signal\", \"--plain\"", src)
        self.assertIn("useListedChannel", src)
        listed = src[src.index("function useListedChannel"):src.index("function startRecord")]
        self.assertIn("selectChannel", listed)
        self.assertNotIn("recordListedShow", listed)
        self.assertIn("function recordListedShow", src)
        self.assertIn("function toggleRecord", src)
        self.assertIn("function startRecord", src)
        self.assertIn("function stopRecord", src)
        self.assertIn("function open()", src)
        self.assertIn("function closeForPopoutSwitch", src)
        self.assertIn("readonly property bool opened:", src)
        self.assertIn("function show():", src)
        self.assertIn("function hide():", src)
        self.assertIn('record", "stop"', src)
        self.assertIn("tvConfigDir", src)
        self.assertIn("../bin/omarchy-tv", src)
        self.assertNotIn('Quickshell.env("HOME") || "") + "/.config/omarchy/tv', src)
        self.assertNotIn('readonly property string binPath: "omarchy-tv"', src)
        self.assertIn("Model.currentProgram(program, root.guideClockMin)", src)
        self.assertIn("chItem.onNow", src)
        self.assertIn("Model.channelSubLine(chItem.stationName, chItem.onNext)", src)
        self.assertIn("Model.airingProgress(chItem.onNow, root.guideClockMin)", src)
        self.assertIn("Model.nextProgram(program, root.guideClockMin)", src)
        self.assertIn("function roomFor", src)
        self.assertIn("function flyoutContentWidth", src)
        self.assertNotIn("function guideBodyHeight", src)
        self.assertIn("property string channelFilter: \"favorites\"", src)
        self.assertNotIn("Watchable", src)
        self.assertIn("text: \"All (\" + (root.watchableChannels ? root.watchableChannels.length : 0)", src)
        self.assertNotIn("Same stations, with Hide", src)
        self.assertIn("? \"Show\" : \"Hide\"", src)
        self.assertIn("hidden.json", src)
        self.assertNotIn("text: \"Dupes", src)
        self.assertIn("text: \"Click to retune this channel\"", src)
        self.assertIn("root.playChannel(root.activeChannelName)", src)
        self.assertIn("tune_status.json", src)
        self.assertIn("root.tuneDisplay", src)
        self.assertIn("root.tunePhase === \"failed\"", src)
        self.assertNotIn("netColor", src)
        self.assertIn("color: chItem.isRecordingHere ? Color.urgent : Color.accent", src)
        self.assertIn("Model.recordDurationArg", src)
        self.assertIn("isLiveSession", src)
        self.assertIn("isLibraryPlayback", src)
        self.assertNotIn("Seek back 15 seconds", src)
        self.assertIn("function barStatusText", src)
        self.assertIn("function barWatchLabel", src)
        self.assertIn("function barRecLabel", src)
        self.assertIn("Model.getDisplayTitle(ch)", src)
        self.assertIn('text: "󰢹"', src)
        self.assertIn('text: "·"', src)
        self.assertIn("color: root.bar.barForeground", src)
        self.assertIn("color: Color.urgent", src)

    def test_guide_strip_uses_lineup_and_omarchy_tokens(self):
        qml = os.path.join(PROJECT_ROOT, "plugin", "BarWidget.qml")
        model = os.path.join(PROJECT_ROOT, "plugin", "Model.js")
        with open(qml, encoding="utf-8") as f:
            src = f.read()
        with open(model, encoding="utf-8") as f:
            js = f.read()
        self.assertIn("root.displayChannels", src)
        self.assertIn("id: guideStripCol", src)
        self.assertIn("guideShowRows", src)
        self.assertIn("Record all", src)
        self.assertIn('"guide", "shows"', src)
        self.assertNotIn("Nothing listed in these hours.", src)
        self.assertIn("placeholderText: \"Search shows and teams\"", src)
        self.assertIn("blocked: guideStripSearch.activeFocus", src)
        self.assertIn("Style.selectedFillFor", src)
        self.assertIn("function showIsOn", js)
        self.assertIn("function recordDurationArg", js)
        self.assertIn("function currentProgram", js)
        self.assertIn("function nextProgram", js)
        self.assertIn("function airingCoversNow", js)
        cover = js[js.index("function coveringProgram"):js.index("function coveringProgram") + 600]
        self.assertIn("airingCoversNow", cover)
        self.assertIn("if (dated) return null", cover)
        self.assertIn("function searchGuide", js)
        self.assertIn("function guideHourBlocks", js)
        self.assertIn("function tvConfigDir", js)
        self.assertIn("function fileUrlToPath", js)
        self.assertNotIn("#F9E2AF", js)
        self.assertNotIn("Qt.darker", src)
        self.assertIn("Color.muted", src)
        self.assertIn("--title", src)
        self.assertIn("guideClockTimer", src)
        self.assertIn("Color.urgent", src)
        self.assertNotIn("guideModalOpen", src)
        self.assertNotIn("guideGridView", src)
        self.assertNotIn("guideKind", src)
        self.assertNotIn("function channelKind", js)
        self.assertNotIn("function guidePlayIdent", js)
        self.assertNotIn("setShowTranslators", src)
        self.assertNotIn("text: \"Dupes", src)
        self.assertNotIn("#a6e3a1", js)


class TestPluginManifest(unittest.TestCase):
    def test_manifest_at_repo_root(self):
        path = os.path.join(PROJECT_ROOT, "manifest.json")
        self.assertTrue(os.path.isfile(path))
        self.assertFalse(os.path.exists(os.path.join(PROJECT_ROOT, "plugin", "manifest.json")))
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["schemaVersion"], 1)
        self.assertEqual(data["id"], "richardb.omarchy-tv")
        self.assertEqual(data["kinds"], ["bar-widget"])
        self.assertEqual(data["entryPoints"]["barWidget"], "plugin/BarWidget.qml")
        self.assertTrue(os.path.isfile(os.path.join(PROJECT_ROOT, "plugin", "BarWidget.qml")))
        self.assertNotIn("..", data["entryPoints"]["barWidget"])
        self.assertEqual(data["barWidget"]["defaultSection"], "right")
        self.assertTrue(data["barWidget"]["description"])


if __name__ == "__main__":
    unittest.main()
