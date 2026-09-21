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
from urllib.parse import unquote

from engine.paths import (
    MPV_SOCKET_PATH,
    CHANNELS_JSON_PATH,
    RECORDINGS_DIR,
    TIMESHIFT_DIR,
    MPV_CHANNELS_CONF,
    PLAYER_STATE_PATH,
    FAVORITES_JSON_PATH,
    UI_PREFS_PATH,
)
from engine.dvr import MIN_PLAYABLE_BYTES
from engine.tuner import TunerManager


def update_player_state(
    running: bool,
    channel: str = "",
    station: str = "",
    pid: int = 0,
    mode: str = "",
    last_live: Optional[str] = None,
    state_path: Optional[str] = None,
) -> None:
    """Writes live playback state atomically for Quickshell UI reactivity."""
    target_path = state_path or PLAYER_STATE_PATH
    prev: Dict[str, Any] = {}
    try:
        if os.path.exists(target_path):
            with open(target_path, "r", encoding="utf-8") as existing:
                data = json.load(existing)
                if isinstance(data, dict):
                    prev = data
    except Exception:
        prev = {}
    kept_live = last_live if last_live is not None else (prev.get("last_live") or "")
    if running and (mode or "live") == "live" and channel:
        kept_live = channel
    try:
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        tmp = f"{target_path}.tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({
                "running": running,
                "channel": channel,
                "station": station,
                "pid": pid,
                "mode": (mode or "live") if running else "",
                "last_live": kept_live,
                "updated_at": time.time()
            }, f, indent=2)
        os.replace(tmp, target_path)
    except Exception:
        pass


def _stated_player_pid(state_path: Optional[str] = None) -> int:
    target_path = state_path or PLAYER_STATE_PATH
    try:
        if not os.path.exists(target_path):
            return 0
        with open(target_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return int(data.get("pid") or 0)
    except Exception:
        return 0
    return 0


def _stated_player_pid_dead(state_path: Optional[str] = None) -> bool:
    pid = _stated_player_pid(state_path)
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return False
    except ProcessLookupError:
        return True
    except PermissionError:
        return False


def _clear_player_state_if_running(state_path: Optional[str] = None) -> None:
    """Clears stale now-playing state when the MPV socket is gone."""
    target_path = state_path or PLAYER_STATE_PATH
    try:
        if not os.path.exists(target_path):
            return
        with open(target_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("running") is True:
            update_player_state(False, state_path=target_path)
    except Exception:
        pass


def parse_dvb_path(path: Optional[str]) -> Optional[str]:
    """Strips dvb:// and URL encoding from an MPV path property."""
    if not isinstance(path, str) or not path.strip():
        return None
    name = path.strip()
    if name.startswith("dvb://"):
        name = name[6:]
    name = unquote(name).strip()
    return name or None


def is_allowed_playback_path(file_path: str) -> bool:
    real_path = os.path.realpath(file_path)
    for folder in (RECORDINGS_DIR, TIMESHIFT_DIR):
        try:
            if os.path.commonpath([os.path.realpath(folder), real_path]) == os.path.realpath(folder):
                return True
        except ValueError:
            continue
    return False


def is_dvb_path(path: Optional[str]) -> bool:
    return isinstance(path, str) and path.strip().lower().startswith("dvb://")


def load_last_live_channel(state_path: Optional[str] = None) -> str:
    target_path = state_path or PLAYER_STATE_PATH
    try:
        if os.path.exists(target_path):
            with open(target_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return str(data.get("last_live") or "").strip()
    except Exception:
        pass
    return ""


def find_channel_index(channels: List[Dict[str, Any]], query: Optional[str]) -> Optional[int]:
    """Returns the playlist index for a live path, or None if it is not in the list."""
    if not channels or not query:
        return None
    from engine.enrichment import match_channel
    matched = match_channel(query, channels)
    if matched:
        for idx, ch in enumerate(channels):
            if ch is matched:
                return idx
        target = matched.get("tune_name") or matched.get("name")
        for idx, ch in enumerate(channels):
            if (ch.get("tune_name") or ch.get("name")) != target:
                continue
            if matched.get("frequency") not in (None, ch.get("frequency")):
                continue
            if matched.get("service_id") not in (None, ch.get("service_id")):
                continue
            return idx
    q = query.strip().lower()
    for idx, ch in enumerate(channels):
        for key in ("tune_name", "name", "raw_name", "callsign", "channel_number"):
            if (ch.get(key) or "").lower() == q:
                return idx
    return None


def channel_index(channels: List[Dict[str, Any]], query: Optional[str]) -> int:
    """Returns the playlist index for a live path, tune name, or channel number."""
    found = find_channel_index(channels, query)
    return 0 if found is None else found


def is_translator_channel(ch: Optional[Dict[str, Any]]) -> bool:
    if not ch:
        return False
    if ch.get("is_translator") is True or ch.get("translator") is True:
        return True
    blob = " ".join([
        str(ch.get("callsign") or ""),
        str(ch.get("display_name") or ""),
        str(ch.get("name") or ""),
    ]).upper()
    return "DRT" in blob or "TRANSLATOR" in blob


def is_favorite_channel(ch: Optional[Dict[str, Any]], favorites: Optional[List[Any]]) -> bool:
    if not ch:
        return False
    favs = {str(item).strip().lower() for item in (favorites or []) if item}
    if not favs:
        return False
    for key in ("name", "tune_name", "raw_name", "callsign", "channel_number", "network"):
        ident = str(ch.get(key) or "").strip().lower()
        if ident and ident in favs:
            return True
    return False


def surfable_channels(
    channels: Optional[List[Dict[str, Any]]],
    favorites: Optional[List[Any]] = None,
    show_translators: bool = False,
    channel_filter: str = "all",
) -> List[Dict[str, Any]]:
    """Channels next/prev may land on — the same list the flyout is showing."""
    want_favs = str(channel_filter or "all").strip().lower() in ("favorites", "favs", "fav")
    pool: List[Dict[str, Any]] = []
    for ch in channels or []:
        if want_favs and not is_favorite_channel(ch, favorites):
            continue
        if not show_translators and is_translator_channel(ch):
            continue
        pool.append(ch)
    return pool


def load_surf_prefs() -> Dict[str, Any]:
    prefs: Dict[str, Any] = {}
    if os.path.exists(UI_PREFS_PATH):
        try:
            with open(UI_PREFS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    prefs = data
        except Exception:
            pass
    return prefs


def load_favorites_list() -> List[Any]:
    if os.path.exists(FAVORITES_JSON_PATH):
        try:
            with open(FAVORITES_JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception:
            pass
    return []


class MpvController:
    def __init__(self, socket_path: str = MPV_SOCKET_PATH):
        self.socket_path = socket_path
        self.proc: Optional[subprocess.Popen] = None
        self.current_channel_index = 0
        self._ipc_id = 0
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
            _clear_player_state_if_running()
            return False
        try:
            res = self.send_command(["get_property", "pid"])
            if res and res.get("error") == "success":
                return True
        except Exception:
            pass
        if _stated_player_pid_dead():
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass
            _clear_player_state_if_running()
        return False

    def reconcile(self) -> bool:
        """Clears now-playing when the TV window was closed outside the plugin."""
        if self.is_running():
            return True
        from engine.timeshift import Timeshift
        Timeshift.stop()
        update_player_state(False)
        return False

    def send_command(self, cmd: List[Any], timeout: float = 1.0) -> Optional[Dict[str, Any]]:
        """Sends a JSON-IPC command and skips unsolicited MPV event lines."""
        if not os.path.exists(self.socket_path):
            return None

        self._ipc_id += 1
        req_id = self._ipc_id
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                deadline = time.time() + timeout
                s.settimeout(timeout)
                s.connect(self.socket_path)
                payload = json.dumps({"command": cmd, "request_id": req_id}) + "\n"
                s.sendall(payload.encode("utf-8"))

                buf = ""
                while time.time() < deadline:
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        break
                    s.settimeout(remaining)
                    try:
                        chunk = s.recv(4096).decode("utf-8")
                    except socket.timeout:
                        break
                    if not chunk:
                        break
                    buf += chunk
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            parsed = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if parsed.get("event"):
                            continue
                        if parsed.get("request_id") == req_id or (
                            "error" in parsed and "request_id" not in parsed
                        ):
                            return parsed
            return None
        except Exception:
            return None

    def launch(self, channel_name: Optional[str] = None, adapter_id: Optional[int] = None) -> bool:
        """Launches MPV instance with Wayland configuration."""
        if self.is_running():
            if self.playback_mode() == "file":
                self.stop()
            else:
                if channel_name:
                    return self.tune(channel_name)
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

        hud_script = os.path.join(os.path.dirname(os.path.realpath(__file__)), "scripts", "tv_hud.lua")
        cli_bin = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "bin", "omarchy-tv")
        cmd = [
            "mpv",
            "--idle=yes",
            f"--input-ipc-server={self.socket_path}",
            "--wayland-app-id=omarchy-tv",
            "--x11-name=omarchy-tv",
            "--title=Omarchy TV",
            "--force-window=immediate",
            "--hwdec=auto-safe",
            "--geometry=1280x720",
            "--keepaspect-window=yes",
            f"--dvbin-card={adapter_id}",
            f"--dvbin-file={MPV_CHANNELS_CONF}",
            "--no-osc",
            f"--script={hud_script}",
            f"--script-opts=tv_hud-cli={cli_bin}",
            "--osd-level=1",
            "--osd-font=sans-serif",
            "--osd-font-size=24",
            "--osd-color=#cdd6f4",
            "--osd-border-color=#11111b",
            "--osd-back-color=#11111b80",
            "--osd-shadow-offset=0",
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
                update_player_state(
                    True,
                    channel=channel_name or "",
                    pid=self.proc.pid if self.proc else 0,
                    mode="live",
                )
                return True
            time.sleep(0.05)

        ready = os.path.exists(self.socket_path)
        if ready:
            update_player_state(
                True,
                channel=channel_name or "",
                pid=self.proc.pid if self.proc else 0,
                mode="live",
            )
        return ready

    def tune(self, channel_name: str) -> bool:
        """Tunes to specified channel name, number, or callsign."""
        from engine.enrichment import match_channel
        from engine.timeshift import Timeshift
        Timeshift.stop()
        self.channels = self._load_channels()
        matched = match_channel(channel_name, self.channels)
        target_name = (matched.get("tune_name") or matched.get("name")) if matched else channel_name

        if matched and matched.get("channel_number"):
            osd_label = f"📺 {matched['channel_number']} {matched.get('display_name', target_name)}"
        else:
            osd_label = f"📺 Tuning {target_name}..."

        if self.is_running() and self.playback_mode() == "file":
            self.stop()

        if not self.is_running():
            return self.launch(target_name)

        res = self.send_command(["loadfile", f"dvb://{target_name}", "replace"])
        self.send_command(["set_property", "pause", False])
        self.show_osd(osd_label)
        success = res is not None and res.get("error") == "success"
        if success:
            update_player_state(
                True,
                channel=target_name,
                station=matched.get("display_name", "") if matched else "",
                pid=self.proc.pid if self.proc else 0,
                mode="live",
            )
        return success

    def play_file(self, file_path: str) -> bool:
        """Plays a local recording in the TV player window, not the live DVB tuner."""
        real_path = os.path.realpath(file_path)
        if not is_allowed_playback_path(real_path):
            return False
        if not os.path.isfile(real_path):
            return False
        if os.path.getsize(real_path) < MIN_PLAYABLE_BYTES:
            return False

        if self.is_running():
            self.stop()
            for _ in range(30):
                if not os.path.exists(self.socket_path):
                    break
                time.sleep(0.05)

        return self.launch_file(real_path)

    def launch_file(self, file_path: str, mode: str = "recording", keep_open: bool = False) -> bool:
        """Starts MPV on a recording without the DVB input module."""
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass

        hud_script = os.path.join(os.path.dirname(os.path.realpath(__file__)), "scripts", "tv_hud.lua")
        cli_bin = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "bin", "omarchy-tv")
        cmd = [
            "mpv",
            f"--input-ipc-server={self.socket_path}",
            "--wayland-app-id=omarchy-tv",
            "--x11-name=omarchy-tv",
            "--title=Omarchy TV",
            "--force-window=immediate",
            "--hwdec=no",
            "--geometry=1280x720",
            "--keepaspect-window=yes",
            "--no-osc",
            f"--script={hud_script}",
            f"--script-opts=tv_hud-cli={cli_bin}",
            "--osd-level=1",
            "--demuxer-lavf-o=scan_all_pmts=1",
        ]
        if keep_open:
            cmd.extend(["--keep-open=yes", "--cache=yes"])
        else:
            cmd.append("--force-seekable=yes")
        cmd.append(file_path)
        self.proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        start_time = time.time()
        while time.time() - start_time < 3.0:
            if os.path.exists(self.socket_path):
                time.sleep(0.1)
                label = os.path.splitext(os.path.basename(file_path))[0].replace("_", " ")
                update_player_state(
                    True,
                    channel=label,
                    station="Recording" if mode != "timeshift" else "Timeshift",
                    pid=self.proc.pid if self.proc else 0,
                    mode=mode,
                )
                return True
            time.sleep(0.05)
        return os.path.exists(self.socket_path)

    def playback_mode(self) -> Optional[str]:
        """Returns 'live', 'file', or None when MPV is not running."""
        if not self.is_running():
            return None
        res = self.send_command(["get_property", "path"])
        path = res.get("data") if res and res.get("error") == "success" else None
        if is_dvb_path(path):
            return "live"
        if isinstance(path, str) and path.strip():
            return "file"
        return "live"

    def return_to_live(self, channel_name: Optional[str] = None) -> bool:
        """Leaves recording/timeshift playback and retunes the live ATSC player."""
        from engine.timeshift import Timeshift
        Timeshift.stop()
        target = (channel_name or "").strip() or load_last_live_channel()
        if not target:
            self.channels = self._load_channels()
            if self.channels:
                target = str(self.channels[0].get("tune_name") or self.channels[0].get("name") or "")
        if not target:
            return False
        return self.tune(target)

    def get_active_channel_name(self) -> Optional[str]:
        """Queries running MPV instance for the currently playing DVB channel."""
        res = self.send_command(["get_property", "path"])
        if res and res.get("error") == "success":
            path = res.get("data")
            if not is_dvb_path(path):
                return None
            return parse_dvb_path(path)
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
        self._surf(1)

    def channel_down(self) -> None:
        """Surfs backward to the previous channel based on current playing station."""
        self._surf(-1)

    def _surf(self, delta: int) -> None:
        self.channels = self._load_channels()
        if not self.channels:
            return
        prefs = load_surf_prefs()
        pool = surfable_channels(
            self.channels,
            favorites=load_favorites_list(),
            show_translators=bool(prefs.get("show_translators")),
            channel_filter=str(prefs.get("channel_filter") or "all"),
        )
        if not pool:
            return
        found = find_channel_index(pool, self.get_active_channel_name())
        if found is None:
            next_idx = 0 if delta > 0 else len(pool) - 1
        else:
            next_idx = (found + delta) % len(pool)
        self.current_channel_index = next_idx
        ch = pool[next_idx]
        self.tune(ch.get("tune_name") or ch.get("name", ""))

    def pause_live(self) -> bool:
        """Freeze live video and start a 15-minute throwaway dump of this channel."""
        from engine.timeshift import Timeshift
        channel = self.get_active_channel_name()
        if not channel:
            return False
        self.send_command(["set_property", "pause", True])
        try:
            Timeshift.start(channel)
        except Exception:
            pass
        self.show_osd("Paused")
        matched = self.get_active_channel_info() or {}
        update_player_state(
            True,
            channel=channel,
            station=matched.get("display_name") or channel,
            pid=self.proc.pid if self.proc else 0,
            mode="live",
        )
        return True

    def resume_timeshift(self) -> bool:
        """Play from the pause point while the dump keeps filling."""
        from engine.timeshift import Timeshift
        path = Timeshift.buffer_path()
        if not path:
            return False
        deadline = time.time() + 5.0
        while time.time() < deadline:
            try:
                if os.path.isfile(path) and os.path.getsize(path) >= MIN_PLAYABLE_BYTES:
                    break
            except OSError:
                pass
            time.sleep(0.1)
        try:
            if not os.path.isfile(path) or os.path.getsize(path) < MIN_PLAYABLE_BYTES:
                self.show_osd("Still paused")
                return False
        except OSError:
            return False
        self.stop(clear_timeshift=False)
        return self.launch_file(path, mode="timeshift", keep_open=True)

    def _live_is_paused(self) -> bool:
        res = self.send_command(["get_property", "pause"])
        return bool(res and res.get("error") == "success" and res.get("data"))

    def toggle_pause(self) -> None:
        mode = self.playback_mode()
        if mode == "live":
            from engine.timeshift import Timeshift
            if Timeshift.is_active() or self._live_is_paused():
                self.resume_timeshift()
            else:
                self.pause_live()
            return
        self.send_command(["cycle", "pause"])

    def seek(self, seconds: float) -> bool:
        if self.playback_mode() != "file":
            return False
        if seconds > 0:
            pos_res = self.send_command(["get_property", "time-pos"])
            dur_res = self.send_command(["get_property", "duration"])
            pos = pos_res.get("data") if pos_res and pos_res.get("error") == "success" else None
            dur = dur_res.get("data") if dur_res and dur_res.get("error") == "success" else None
            if isinstance(pos, (int, float)) and isinstance(dur, (int, float)) and dur > 0:
                if float(pos) + seconds >= float(dur) - 0.25:
                    return self.return_to_live()
        res = self.send_command(["seek", seconds, "relative"])
        return res is not None and res.get("error") == "success"

    def toggle_fullscreen(self) -> None:
        subprocess.Popen(
            [
                "hyprctl",
                "eval",
                'hl.dispatch(hl.dsp.window.fullscreen({ mode = "fullscreen", action = "toggle", layout_aware = false, window = "class:^(omarchy-tv)$" }))',
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    def show_osd(self, text: str, duration_ms: int = 3000) -> None:
        self.send_command(["show-text", text, str(duration_ms)])

    def _wait_until_stopped(self, timeout: float = 2.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not os.path.exists(self.socket_path):
                break
            time.sleep(0.05)
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass
        if self.proc is not None:
            try:
                self.proc.wait(timeout=0.2)
            except Exception:
                pass
            self.proc = None

    def stop(self, clear_timeshift: bool = True) -> None:
        if self.is_running():
            self.send_command(["quit"])
        self._wait_until_stopped()
        if clear_timeshift:
            from engine.timeshift import Timeshift
            Timeshift.stop()
        update_player_state(False)


if __name__ == "__main__":
    controller = MpvController()
    print("MPV Running:", controller.is_running())
