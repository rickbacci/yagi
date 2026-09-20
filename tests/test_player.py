"""
Unit tests for Omarchy TV - MPV Player Controller & Channel Cycling
"""

import os
import json
import unittest
import tempfile
from unittest.mock import patch, MagicMock

from player.controller import MpvController, update_player_state
from engine.tuner import TunerAdapter


class TestMpvPlayerController(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.state_path = os.path.join(self.tmp_dir.name, "player_state.json")
        self._state_patcher = patch("player.controller.PLAYER_STATE_PATH", self.state_path)
        self._state_patcher.start()

        self.mock_channels = [
            {"id": "53.1", "name": "53.1 Daystar", "frequency": 177028615},
            {"id": "53.2", "name": "53.2 WCDN", "frequency": 177028615},
            {"id": "7.1", "name": "7.1 WABC", "frequency": 177028615},
        ]
        self.controller = MpvController(socket_path=os.path.join(self.tmp_dir.name, "mpv.sock"))
        self.controller._load_channels = MagicMock(return_value=self.mock_channels)
        self.controller.channels = self.mock_channels

    def tearDown(self):
        self._state_patcher.stop()
        self.tmp_dir.cleanup()

    def test_channel_load(self):
        self.assertEqual(len(self.controller.channels), 3)
        self.assertEqual(self.controller.channels[0]["name"], "53.1 Daystar")

    @patch.object(MpvController, "tune")
    @patch.object(MpvController, "get_active_channel_name")
    def test_channel_up_stateless_cycling(self, mock_active, mock_tune):
        # When currently playing channel index 0 (53.1 Daystar)
        mock_active.return_value = "53.1 Daystar"
        self.controller.channel_up()
        mock_tune.assert_called_with("53.2 WCDN")
        self.assertEqual(self.controller.current_channel_index, 1)

        # When currently playing channel index 1 (53.2 WCDN)
        mock_active.return_value = "53.2 WCDN"
        self.controller.channel_up()
        mock_tune.assert_called_with("7.1 WABC")
        self.assertEqual(self.controller.current_channel_index, 2)

        # Wraparound from last channel (7.1 WABC) back to index 0
        mock_active.return_value = "7.1 WABC"
        self.controller.channel_up()
        mock_tune.assert_called_with("53.1 Daystar")
        self.assertEqual(self.controller.current_channel_index, 0)

    @patch.object(MpvController, "tune")
    @patch.object(MpvController, "get_active_channel_name")
    def test_channel_down_stateless_cycling(self, mock_active, mock_tune):
        # Starting at channel index 0, channel_down should wrap to index 2 (7.1 WABC)
        mock_active.return_value = "53.1 Daystar"
        self.controller.channel_down()
        mock_tune.assert_called_with("7.1 WABC")
        self.assertEqual(self.controller.current_channel_index, 2)

        # Stepping down from index 2 moves to index 1 (53.2 WCDN)
        mock_active.return_value = "7.1 WABC"
        self.controller.channel_down()
        mock_tune.assert_called_with("53.2 WCDN")
        self.assertEqual(self.controller.current_channel_index, 1)

    @patch.object(MpvController, "is_running", return_value=True)
    @patch.object(MpvController, "send_command")
    def test_get_active_channel_name_parsing(self, mock_send, mock_running):
        mock_send.return_value = {"error": "success", "data": "dvb://53.2 WCDN"}
        active = self.controller.get_active_channel_name()
        self.assertEqual(active, "53.2 WCDN")
        mock_send.assert_called_with(["get_property", "path"])

    @patch.object(MpvController, "is_running", return_value=False)
    def test_get_active_channel_name_when_offline(self, mock_running):
        active = self.controller.get_active_channel_name()
        self.assertIsNone(active)

    @patch.object(MpvController, "is_running", return_value=False)
    @patch("engine.tuner.TunerManager.get_available_tuner")
    @patch("subprocess.Popen")
    @patch("os.path.exists", return_value=True)
    def test_dynamic_adapter_allocation(self, mock_exists, mock_popen, mock_get_tuner, mock_running):
        # Simulate tuner 0 is busy, tuner 1 is free
        mock_adapter = MagicMock()
        mock_adapter.adapter_id = 1
        mock_get_tuner.return_value = mock_adapter

        self.controller.launch(channel_name="53.1 Daystar", adapter_id=None)

        # Verify MPV command received --dvbin-card=1
        cmd_called = mock_popen.call_args[0][0]
        self.assertIn("--dvbin-card=1", cmd_called)
        self.assertIn("dvb://53.1 Daystar", cmd_called)

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

    @patch("player.controller.update_player_state")
    @patch.object(MpvController, "send_command", return_value=None)
    def test_is_running_does_not_clear_state_on_ipc_failure(self, mock_send, mock_update):
        with patch("os.path.exists", return_value=True):
            running = self.controller.is_running()
        self.assertFalse(running)
        mock_update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
