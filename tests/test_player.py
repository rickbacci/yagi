"""
Unit tests for Omarchy TV - MPV Player Controller & Channel Cycling
"""

import os
import json
import socket
import subprocess
import sys
import threading
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
)
from engine.enrichment import enrich_and_sort_channels
from engine.timeshift import Timeshift


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
LUA_HUD = os.path.join(PROJECT_ROOT, "player", "scripts", "tv_hud.lua")
CLI_BIN = os.path.join(PROJECT_ROOT, "bin", "omarchy-tv")


ENRICHED_CHANNELS = enrich_and_sort_channels([
    {"name": "WKYC-HD", "raw_name": "WKYC-HD", "frequency": 503028615, "service_id": 1},
    {"name": "WEWSHD", "raw_name": "WEWSHD", "frequency": 479028615, "service_id": 3},
    {"name": "FOX", "raw_name": "FOX", "frequency": 183028615, "service_id": 3},
    {"name": "COZI TV", "raw_name": "COZI TV", "frequency": 503028615, "service_id": 3},
])


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
            return_value={"show_translators": True, "channel_filter": "all"},
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
        self._reap_patcher = patch.object(MpvController, "_reap_stale_window")
        self._reap_patcher.start()

    def tearDown(self):
        self._reap_patcher.stop()
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

    @patch("player.controller.is_timeshift_path", return_value=True)
    @patch("player.controller.Timeshift.start_dump")
    @patch("player.controller.Timeshift.start_follow")
    @patch.object(MpvController, "is_running", return_value=False)
    @patch("subprocess.Popen")
    @patch("os.path.exists", return_value=True)
    def test_live_launch_plays_dump_file_not_dvbin(self, mock_exists, mock_popen, mock_running, mock_follow, mock_dump, _ts_path):
        dump = os.path.join(self.tmp_dir.name, "live.ts")
        with open(dump, "wb") as f:
            f.write(b"x" * (256 * 1024))
        mock_dump.return_value = dump
        follow = MagicMock()
        follow.stdout = MagicMock()
        mock_follow.return_value = follow
        mock_popen.return_value = MagicMock(pid=9)

        self.controller.launch(channel_name="53.1 Daystar", adapter_id=None)

        mock_dump.assert_called_once()
        mock_follow.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        self.assertIn("--force-window=immediate", cmd)
        self.assertNotIn("--idle=yes", cmd)
        self.assertFalse(any(str(arg).startswith("--dvbin-") for arg in cmd))
        self.assertEqual(cmd[-1], "-")
        self.assertIn("--demuxer-lavf-format=mpegts", cmd)
        self.assertTrue(any("tv_hud-timeshift-file=" in str(arg) for arg in cmd))
        self.assertTrue(any("tv_hud-follow-sock=" in str(arg) for arg in cmd))
        self.assertTrue(any(str(arg).startswith("--script-opts=tv_hud-cli=") for arg in cmd))

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
            return_value={"show_translators": True, "channel_filter": "all"},
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
        self._reap_patcher = patch.object(MpvController, "_reap_stale_window")
        self._reap_patcher.start()
        self.server = FakeMpvIpc(self.controller.socket_path, path_value=self.dump_path)
        self.server.start()

    def tearDown(self):
        self.server.stop()
        self._reap_patcher.stop()
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

    def test_channel_up_loadfiles_timeshift_dump(self):
        with patch.object(self.controller, "launch_file", return_value=True) as mock_launch:
            self.controller.channel_up()
        mock_launch.assert_called()
        self.assertEqual(mock_launch.call_args[0][0], self.dump_path)
        self.assertFalse(any(str(item).startswith("dvb://") for item in mock_launch.call_args[0]))
        self.assertEqual(self.controller.current_channel_index, 1)

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

    def test_return_to_live_from_live_seeks_write_head(self):
        self.assertTrue(self.controller.return_to_live())
        sent = [m.get("command") for m in self.server.commands]
        self.assertIn(["script-message", "tv-live-edge"], sent)
        self.assertIn(["set_property", "pause", False], sent)

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

    def test_pause_cycles_mpv_pause(self):
        self.controller.toggle_pause()
        sent = [m.get("command") for m in self.server.commands]
        self.assertIn(["cycle", "pause"], sent)

    def test_seek_asks_hud(self):
        rec = os.path.join(self.tmp_dir.name, "show.ts")
        self.server.path_value = rec
        self.assertTrue(self.controller.seek(15))
        sent = [m.get("command") for m in self.server.commands]
        self.assertIn(["script-message", "tv-seek", "15"], sent)

    def test_channel_down_wraps_to_last_station(self):
        with patch.object(self.controller, "launch_file", return_value=True) as mock_launch:
            self.controller.channel_down()
        self.assertEqual(mock_launch.call_args[0][0], self.dump_path)
        self.assertEqual(self.controller.current_channel_index, len(ENRICHED_CHANNELS) - 1)

    def test_channel_up_from_url_encoded_cozi(self):
        self._ch_patcher.stop()
        self._ch_patcher = patch("player.controller.Timeshift.current_channel", return_value="COZI TV")
        self._ch_patcher.start()
        with patch.object(self.controller, "launch_file", return_value=True) as mock_launch:
            self.controller.channel_up()
        self.assertEqual(mock_launch.call_args[0][0], self.dump_path)


class TestLuaChannelKeys(unittest.TestCase):
    def test_jk_surf_inside_mpv_not_via_blocking_cli(self):
        with open(LUA_HUD, encoding="utf-8") as f:
            src = f.read()
        self.assertIn('mp.add_forced_key_binding("j", "tv_surf_prev_j", surf_prev)', src)
        self.assertIn('mp.add_forced_key_binding("k", "tv_surf_next_k", surf_next)', src)
        self.assertIn('mp.commandv("loadfile"', src)
        self.assertIn("is_timeshift_playback", src)
        self.assertIn("is_library_playback", src)
        self.assertIn("timeshift_behind", src)
        self.assertIn("tv_return_live", src)
        self.assertIn('"live"', src)
        self.assertIn("tv_pause", src)
        self.assertIn("request_pause", src)
        self.assertIn("end-file", src)
        self.assertIn("request_live", src)
        self.assertIn("seek_live_edge", src)
        self.assertIn("behind_live", src)
        self.assertIn("tv-live-edge", src)
        self.assertIn('delta > 0 and "next" or "prev"', src)
        self.assertIn('mp.commandv("set", "pause", "no")', src)
        self.assertIn("seek", src)
        self.assertIn("go_live", src)
        self.assertIn("eof-reached", src)
        self.assertIn("ATSC_BPS", src)
        self.assertIn("virt_pos", src)
        self.assertIn("atsc_duration", src)
        self.assertIn("tv_cli", src)
        self.assertIn("local function surf_next()\n    surf(1)\nend", src)
        self.assertIn("if is_file_playback() then", src)
        self.assertIn("timeshift_active.json", src)
        self.assertIn("SEEK_STEP = 15", src)
        self.assertIn("file_progress", src)
        self.assertIn("file_bytes", src)
        self.assertIn("apply_virt_seek", src)
        self.assertIn("send_follow_seek", src)
        self.assertIn("timeshift-file", src)
        self.assertIn("follow-sock", src)
        self.assertIn("pcall(show_hud)", src)
        self.assertIn("show_hud:", src)
        self.assertIn("prog.end_time or", src)
        self.assertIn("live_overlay", src)
        self.assertIn("render_live_badge", src)
        self.assertIn("do not slam the bar", src)
        self.assertIn("if is_timeshift_playback() then", src)
        self.assertIn("seek_reload", src)
        self.assertIn('register_script_message("tv-seek"', src)
        self.assertIn('start = "#" .. tostring(bytes)', src)
        self.assertIn("&H0000FF&", src)
        self.assertIn("prev_was_file", src)
        self.assertIn("pos(640,360)", src)
        self.assertIn("fs48", src)
        self.assertIn("live_flash_until", src)
        self.assertIn("pending_live_flash", src)
        self.assertIn("Pause buffer", src)
        self.assertNotIn("Unseekable live buffer", src)
        self.assertNotIn("drop-buffers", src)
        self.assertNotIn('mp.command("cycle fullscreen")', src)
        self.assertIn("video-codec", src)
        self.assertIn("show_live_badge", src)
        self.assertIn("joined_live_flash", src)
        self.assertIn("osd_message", src)
        self.assertIn('"LIVE"', src)
        self.assertIn('"record", "stop"', src)
        self.assertIn("MBTN_LEFT_DBL", src)
        self.assertIn("toggle_window_fullscreen", src)
        self.assertIn("hyprctl", src)
        self.assertIn("LIVE_SLACK", src)
        self.assertIn("is_library_playback()", src)


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
        self.assertIn("sync", res.stdout)


class TestPluginSessionCards(unittest.TestCase):
    def test_watch_and_record_are_separate_cards(self):
        qml = os.path.join(PROJECT_ROOT, "plugin", "BarWidget.qml")
        with open(qml, encoding="utf-8") as f:
            src = f.read()
        self.assertIn("model: root.activeRecordings", src)
        self.assertIn("anchors.right: parent.right", src)
        self.assertIn("text: root.watchModeLabel", src)
        self.assertIn("text: \"REC\"", src)
        self.assertIn("Stop this recording", src)
        self.assertIn("isLiveSession", src)
        self.assertIn("isLibraryPlayback", src)


if __name__ == "__main__":
    unittest.main()
