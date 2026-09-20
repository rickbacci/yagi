"""
Omarchy TV - MPV Player Controller & IPC Manager
Launches MPV with Wayland hardware decoding, Hyprland window rules, and JSON IPC.
"""

import os
import sys
import json
import time
import socket
import subprocess
from typing import Optional, Dict, Any, List

from engine.paths import MPV_SOCKET_PATH, CHANNELS_JSON_PATH, RECORDINGS_DIR, MPV_CHANNELS_CONF
from engine.tuner import TunerManager


class MpvController:
    def __init__(self, socket_path: str = MPV_SOCKET_PATH):
        self.socket_path = socket_path
        self.proc: Optional[subprocess.Popen] = None
        self.current_channel_index = 0
        self.channels = self._load_channels()

    def _load_channels(self) -> List[Dict[str, Any]]:
        if os.path.exists(CHANNELS_JSON_PATH):
            try:
                with open(CHANNELS_JSON_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("channels", [])
            except Exception:
                pass
        return []

    def is_running(self) -> bool:
        if not os.path.exists(self.socket_path):
            return False
        try:
            res = self.send_command(["get_property", "playback-time"])
            return res is not None
        except Exception:
            return False

    def send_command(self, cmd: List[Any], timeout: float = 1.0) -> Optional[Dict[str, Any]]:
        """Sends a JSON-IPC command to MPV socket."""
        if not os.path.exists(self.socket_path):
            return None

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                s.connect(self.socket_path)
                payload = json.dumps({"command": cmd}) + "\n"
                s.sendall(payload.encode("utf-8"))

                response = ""
                while True:
                    chunk = s.recv(4096).decode("utf-8")
                    if not chunk:
                        break
                    response += chunk
                    if "\n" in chunk:
                        break

            # Parse JSON line
            for line in response.splitlines():
                line = line.strip()
                if line:
                    try:
                        parsed = json.loads(line)
                        if "error" in parsed:
                            return parsed
                    except json.JSONDecodeError:
                        continue
            return None
        except Exception:
            return None

    def launch(self, channel_name: Optional[str] = None, adapter_id: Optional[int] = None) -> bool:
        """Launches MPV instance with Wayland configuration."""
        if self.is_running():
            if channel_name:
                self.tune(channel_name)
            return True

        # Dynamic tuner allocation: select first available ATSC tuner if not specified
        if adapter_id is None:
            available = TunerManager.get_available_tuner(require_atsc=True)
            adapter_id = available.adapter_id if available else 0

        # Remove old dead socket if exists
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass

        cmd = [
            "mpv",
            "--idle=yes",
            f"--input-ipc-server={self.socket_path}",
            "--wayland-app-id=omarchy-tv",
            "--x11-name=omarchy-tv",
            "--title=Omarchy TV",
            "--force-window=immediate",
            "--hwdec=auto-safe",
            "--geometry=720x405",
            "--keepaspect-window=yes",
            f"--dvbin-card={adapter_id}",
            f"--dvbin-file={MPV_CHANNELS_CONF}",
            "--osd-level=1",
            "--osd-font=sans-serif",
            "--osd-font-size=28",
            "--osd-color=#cdd6f4",
            "--osd-border-color=#11111b",
        ]

        if channel_name:
            cmd.append(f"dvb://{channel_name}")

        self.proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True
        )

        # Wait up to 3 seconds for socket to become ready
        start_time = time.time()
        while time.time() - start_time < 3.0:
            if os.path.exists(self.socket_path):
                time.sleep(0.1)
                return True
            time.sleep(0.05)

        return os.path.exists(self.socket_path)

    def tune(self, channel_name: str) -> bool:
        """Tunes to specified channel name, number, or callsign."""
        from engine.enrichment import match_channel
        self.channels = self._load_channels()
        matched = match_channel(channel_name, self.channels)
        target_name = (matched.get("tune_name") or matched.get("name")) if matched else channel_name

        if matched and matched.get("channel_number"):
            osd_label = f"📺 {matched['channel_number']} {matched.get('display_name', target_name)}"
        else:
            osd_label = f"📺 Tuning {target_name}..."

        if not self.is_running():
            return self.launch(target_name)

        res = self.send_command(["loadfile", f"dvb://{target_name}", "replace"])
        self.show_osd(osd_label)
        return res is not None and res.get("error") == "success"

    def get_active_channel_name(self) -> Optional[str]:
        """Queries running MPV instance for the currently playing DVB channel."""
        if not self.is_running():
            return None
        res = self.send_command(["get_property", "path"])
        if res and res.get("error") == "success":
            data = res.get("data")
            if isinstance(data, str) and data.startswith("dvb://"):
                return data.replace("dvb://", "", 1)
        return None

    def get_active_channel_info(self) -> Optional[Dict[str, Any]]:
        """Returns full enriched metadata for the currently playing channel."""
        active_name = self.get_active_channel_name()
        if not active_name:
            return None
        from engine.enrichment import match_channel
        self.channels = self._load_channels()
        return match_channel(active_name, self.channels)

    def channel_up(self) -> None:
        """Surfs forward to the next channel based on current playing station."""
        self.channels = self._load_channels()
        if not self.channels:
            return

        active_name = self.get_active_channel_name()
        current_idx = 0
        if active_name:
            for idx, ch in enumerate(self.channels):
                if ch.get("name") == active_name or ch.get("tune_name") == active_name:
                    current_idx = idx
                    break

        next_idx = (current_idx + 1) % len(self.channels)
        self.current_channel_index = next_idx
        ch = self.channels[next_idx]
        self.tune(ch.get("tune_name") or ch.get("name", ""))

    def channel_down(self) -> None:
        """Surfs backward to the previous channel based on current playing station."""
        self.channels = self._load_channels()
        if not self.channels:
            return

        active_name = self.get_active_channel_name()
        current_idx = 0
        if active_name:
            for idx, ch in enumerate(self.channels):
                if ch.get("name") == active_name or ch.get("tune_name") == active_name:
                    current_idx = idx
                    break

        prev_idx = (current_idx - 1) % len(self.channels)
        self.current_channel_index = prev_idx
        ch = self.channels[prev_idx]
        self.tune(ch.get("tune_name") or ch.get("name", ""))

    def toggle_pause(self) -> None:
        self.send_command(["cycle", "pause"])

    def toggle_fullscreen(self) -> None:
        self.send_command(["cycle", "fullscreen"])

    def show_osd(self, text: str, duration_ms: int = 3000) -> None:
        self.send_command(["show-text", text, str(duration_ms)])

    def stop(self) -> None:
        if self.is_running():
            self.send_command(["quit"])


if __name__ == "__main__":
    controller = MpvController()
    print("MPV Running:", controller.is_running())
