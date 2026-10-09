"""
Yagi - MPV Player Controller & IPC Manager
Launches MPV with Wayland hardware decoding, Hyprland window rules, and JSON IPC.
"""

import os
import sys
import json
import time
import fcntl
import select
import signal
import socket
import subprocess
from typing import Optional, Dict, Any, List
from urllib.parse import unquote

from engine.paths import (
    MPV_SOCKET_PATH,
    CHANNELS_JSON_PATH,
    RECORDINGS_DIR,
    PLAYER_STATE_PATH,
    FAVORITES_JSON_PATH,
    UI_PREFS_PATH,
    FOLLOW_FIFO_PATH,
    FOLLOW_SOCKET_PATH,
    LIVE_SLICE,
    TIMESHIFT_DIR,
    chmod_private_file,
    in_unit,
    own_scope,
    stop_unit,
    touch_private_file,
)
from engine.dvr import MIN_PLAYABLE_BYTES
from engine.hidden import is_hidden_channel, load_hidden
from engine.pool import BothTunersBusy
from engine.timeshift import (
    LIVE_SLACK,
    Timeshift,
    align_ts,
    is_timeshift_path,
)
from player.transport import Transport

# Dump lock plus lua/lavf can outrun a 3s IPC poll. The flyout treats a
# non-zero CLI as "TV didn't open" even if mpv is still coming up.
LAUNCH_SOCKET_WAIT_SECS = 12.0

# The follower writes as soon as the dump has bytes. Past this, it is stuck or dead.
FOLLOW_OPEN_WAIT_SECS = 6.0


def _open_follow_reader(fifo_path: str, follow_pid: int, timeout: float = FOLLOW_OPEN_WAIT_SECS) -> Optional[int]:
    """Read end of the follow fifo, once the follower has sent its first bytes.

    A blocking open never returns if the follower dies before its own open.
    The fd goes back to blocking so mpv reads it like a plain pipe.
    """
    try:
        fd = os.open(fifo_path, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return None
    poller = select.poll()
    poller.register(fd, select.POLLIN)
    deadline = time.time() + timeout
    while time.time() < deadline:
        events = poller.poll(50)
        if any(ev & select.POLLIN for _, ev in events):
            flags = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)
            return fd
        if events or not Timeshift._pid_alive(follow_pid):
            break
    os.close(fd)
    return None


# Same lua as /usr/share/omarchy/default/hypr/bindings/tiling.lua Super+F.
OMARCHY_FULLSCREEN_LUA = 'hl.dsp.window.fullscreen({ mode = "fullscreen" })'


def _hypr_json(subcommand: str):
    result = subprocess.run(
        ["hyprctl", subcommand, "-j"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        err = (result.stdout + result.stderr).strip()
        print(f"hyprctl {subcommand} -j failed: {err}", file=sys.stderr)
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        print(f"hyprctl {subcommand} -j: {exc}", file=sys.stderr)
        return None


def focus_tv_window(wait: float = 3.0) -> bool:
    """Keyboard focus to the TV window, so the HUD keys work. A new window takes a moment to map."""
    deadline = time.time() + wait
    while True:
        clients = _hypr_json("clients") or []
        if any(isinstance(c, dict) and c.get("class") == "yagi" for c in clients):
            return _hypr_dispatch('hl.dsp.focus({ window = "class:^yagi$" })')
        if time.time() >= deadline:
            return False
        time.sleep(0.2)


def _hypr_dispatch(lua: str) -> bool:
    result = subprocess.run(
        ["hyprctl", "dispatch", lua],
        capture_output=True,
        text=True,
    )
    out = (result.stdout + result.stderr).strip()
    if result.returncode != 0 or (out and out != "ok"):
        print(f"hyprctl dispatch {lua!r} failed: {out}", file=sys.stderr)
        return False
    return True


def _hypr_tv_client():
    clients = _hypr_json("clients") or []
    return next(
        (c for c in clients if isinstance(c, dict) and c.get("class") == "yagi"),
        None,
    )


def _toggle_omarchy_fullscreen(target_tv: bool = False) -> None:
    """Unpin the Yagi window if needed, then the same fullscreen dispatcher Omarchy Super+F uses.

    Pin is a static window-rule effect. Super+F on a pinned client stays at
    fullscreen 0 (measured on this Hyprland). Super+F special-cases the PiP
    when it is the focused window. `--player` targets the TV window from CLI.
    """
    active = _hypr_json("activewindow") or {}
    target = active if active.get("class") == "yagi" else None
    if target_tv and target is None:
        target = _hypr_tv_client()
    addr = (target or {}).get("address")
    is_tv = bool(addr)
    pinned = bool((target or {}).get("pinned"))
    was_fs = int((target or {}).get("fullscreen") or 0) != 0
    win = f', window = "address:{addr}"' if is_tv else ""
    if is_tv and pinned and not was_fs:
        _hypr_dispatch(f'hl.dsp.window.pin({{ window = "address:{addr}" }})')
    if is_tv:
        _hypr_dispatch(f'hl.dsp.window.fullscreen({{ mode = "fullscreen"{win} }})')
    else:
        _hypr_dispatch(OMARCHY_FULLSCREEN_LUA)
    if not is_tv or not was_fs:
        return
    after = _hypr_tv_client() or {}
    if int(after.get("fullscreen") or 0) == 0 and not after.get("pinned"):
        _hypr_dispatch(f'hl.dsp.window.pin({{ window = "address:{addr}" }})')


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


def _is_tv_window(pid: int) -> bool:
    """A living yagi mpv. A reused pid is some other program."""
    if pid <= 1:
        return False
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            args = f.read().split(b"\0")
    except OSError:
        return False
    return b"--wayland-app-id=yagi" in args


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
    try:
        return os.path.commonpath([os.path.realpath(RECORDINGS_DIR), real_path]) == os.path.realpath(RECORDINGS_DIR)
    except ValueError:
        return False


def is_dvb_path(path: Optional[str]) -> bool:
    return isinstance(path, str) and path.strip().lower().startswith("dvb://")


def is_follow_path(path: Optional[str]) -> bool:
    if not isinstance(path, str) or not path.strip():
        return False
    p = path.strip()
    low = p.lower()
    if low in ("-", "fd://0", "fdclose://0", "/dev/stdin"):
        return True
    if p == FOLLOW_FIFO_PATH or p.endswith("yagi-follow.fifo"):
        return True
    return False


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


def is_favorite_channel(ch: Optional[Dict[str, Any]], favorites: Optional[List[Any]]) -> bool:
    from engine.favorites import is_favorite
    return is_favorite(ch, favorites)


def surfable_channels(
    channels: Optional[List[Dict[str, Any]]],
    favorites: Optional[List[Any]] = None,
    channel_filter: str = "favorites",
    hidden: Optional[List[Any]] = None,
) -> List[Dict[str, Any]]:
    """Channels next/prev may land on. Hidden stations stay off every surf list."""
    want_favs = str(channel_filter or "favorites").strip().lower() in ("favorites", "favs", "fav")
    pool: List[Dict[str, Any]] = []
    for ch in channels or []:
        if is_hidden_channel(ch, hidden):
            continue
        if want_favs and not is_favorite_channel(ch, favorites):
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
    from engine.favorites import load_favorites
    return load_favorites(FAVORITES_JSON_PATH)


class MpvController:
    def __init__(self, socket_path: str = MPV_SOCKET_PATH):
        self.socket_path = socket_path
        self.proc: Optional[subprocess.Popen] = None
        self.current_channel_index = 0
        self.transport = Transport(self)
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
        """Clears now-playing when the TV window was closed outside the plugin.

        A window that is alive but slow to answer IPC keeps its pause.
        """
        if Timeshift.tune_lock_held():
            return True
        window = _stated_player_pid()
        if self.is_running():
            Timeshift.hold_dump_if_full()
            return True
        if _is_tv_window(window):
            return True
        Timeshift.wipe()
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
        """Starts live dump + file playback, or retunes if the window is already up."""
        if self.is_running():
            if self.playback_mode() == "file":
                self.stop()
            elif channel_name:
                return self.tune(channel_name, adapter_id=adapter_id)
            else:
                return True
        if not channel_name:
            return False
        return self.tune(channel_name, adapter_id=adapter_id)

    def relaunch_pip(self, channel: str, station: str = "") -> bool:
        """Quit the old PiP, then open a new one on the dump already filling."""
        for _ in range(40):
            if Timeshift.acquire_tune_lock():
                break
            time.sleep(0.05)
        else:
            return False
        try:
            state = Timeshift.load_state()
            dump_path = state.get("path") or ""
            if not dump_path or not os.path.isfile(dump_path):
                dump_path = os.path.join(TIMESHIFT_DIR, "live.ts")
            if self.is_running():
                self.send_command(["quit"])
                self._wait_until_stopped()
            else:
                self._reap_stale_window()
            return self.launch_file(
                dump_path,
                mode="live",
                channel=channel,
                station=station,
            )
        finally:
            Timeshift.release_tune_lock()

    def tune(self, channel_name: str, adapter_id: Optional[int] = None) -> bool:
        """Dumps the station to live.ts. A live PiP remaps after the new dump exists."""
        from engine.enrichment import match_channel

        keep_window = self.is_running() and self.playback_mode() == "live"
        if not Timeshift.acquire_tune_lock():
            return False
        opened = False
        try:
            self.channels = self._load_channels()
            matched = match_channel(channel_name, self.channels)
            target_name = Timeshift.conf_name(matched) if matched else channel_name
            station = matched.get("display_name", "") if matched else ""
            Timeshift.begin_tune(target_name, station)

            if keep_window and Timeshift.switch_program(target_name):
                Timeshift.finish_tune()
                state = Timeshift.load_state()
                if state.get("paused") or str(state.get("view") or "live") != "live":
                    self.transport.seek_cursor(Timeshift.live_join_byte(), paused=False)
                self.send_command(["script-message", "tv-program"])
                update_player_state(
                    True,
                    channel=target_name,
                    station=station,
                    pid=_stated_player_pid(),
                    mode="live",
                )
                return True

            if keep_window:
                self.send_command(["script-message", "tv-blank"])
                if Timeshift.note_channel(target_name):
                    update_player_state(
                        True,
                        channel=target_name,
                        station=station,
                        pid=_stated_player_pid(),
                        mode="live",
                    )
                    self.send_command(["script-message", "tv-retuned"])
                dump_path = Timeshift.retune_keep_window(target_name)
            else:
                try:
                    dump_path = Timeshift.start_dump(target_name)
                except BothTunersBusy as exc:
                    Timeshift.fail_tune(target_name, station, message=str(exc))
                    return False
            if not dump_path:
                if keep_window:
                    self.send_command(["script-message", "tv-unblank"])
                Timeshift.fail_tune(target_name, station)
                return False
            Timeshift.finish_tune()

            if keep_window:
                self.send_command(["script-message", "tv-retuned"])
                self.open_timeshift_dump(Timeshift.picture_open_byte(), paused=False)
                opened = True
                update_player_state(
                    True,
                    channel=target_name,
                    station=station,
                    pid=_stated_player_pid(),
                    mode="live",
                )
                return True
            ok = self.launch_file(
                dump_path,
                mode="live",
                channel=target_name,
                station=station,
            )
            if not ok:
                Timeshift.wipe()
            return ok
        finally:
            Timeshift.release_tune_lock()
            if keep_window and not opened:
                self.send_command(["script-message", "tv-unblank"])

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

    def _reap_stale_window(self) -> None:
        """Kills a leftover PiP on our IPC socket that is not answering it."""
        if self.is_running():
            return
        pids = set()
        stated = _stated_player_pid()
        if stated > 0:
            pids.add(stated)
        ours = f"--input-ipc-server={self.socket_path}"
        try:
            out = subprocess.check_output(
                ["pgrep", "-a", "mpv"],
                stderr=subprocess.DEVNULL,
                text=True,
            )
            for line in out.splitlines():
                args = line.split()
                if "--wayland-app-id=yagi" not in args or ours not in args:
                    continue
                try:
                    pids.add(int(line.split(None, 1)[0]))
                except ValueError:
                    pass
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            pass
        dump_pid = int(Timeshift.load_state().get("pid") or 0)
        follow_pid = int(Timeshift.load_state().get("follow_pid") or 0)
        my_pid = os.getpid()
        for pid in pids:
            if pid <= 1 or pid in (my_pid, dump_pid, follow_pid):
                continue
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
        deadline = time.time() + 1.2
        while time.time() < deadline:
            alive = False
            for pid in list(pids):
                if pid in (dump_pid, follow_pid, my_pid):
                    continue
                try:
                    os.kill(pid, 0)
                    alive = True
                except OSError:
                    pids.discard(pid)
            if not alive:
                break
            time.sleep(0.05)
        for pid in list(pids):
            if pid in (dump_pid, follow_pid, my_pid):
                continue
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass

    def launch_file(
        self,
        file_path: str,
        mode: str = "recording",
        channel: str = "",
        station: str = "",
    ) -> bool:
        """Starts MPV on a file or the live follow pipe, never dvbin."""
        if self.is_running():
            self.send_command(["quit"])
            self._wait_until_stopped()
        else:
            self._reap_stale_window()

        hud_script = os.path.join(os.path.dirname(os.path.realpath(__file__)), "scripts", "tv_hud.lua")
        cli_bin = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "bin", "yagi")
        live_dump = is_timeshift_path(file_path)
        cmd = [
            "mpv",
            f"--input-ipc-server={self.socket_path}",
            "--wayland-app-id=yagi",
            "--x11-name=yagi",
            "--title=Yagi",
            "--force-window=immediate",
            "--hwdec=auto-safe",
            "--keepaspect-window=no",
            "--window-dragging=no",
            "--no-osc",
            "--osd-bar=no",
            "--osd-on-seek=no",
            "--input-default-bindings=no",
            f"--script={hud_script}",
            "--osd-level=0",
            "--mute=yes",
            "--sub-create-cc-track=yes",
            "--slang=eng",
            "--subs-fallback=yes",
            "--demuxer-lavf-analyzeduration=2",
            "--demuxer-lavf-o=fflags=+genpts+discardcorrupt",
            "--cache=yes",
        ]
        stdin = subprocess.DEVNULL
        script_opts = [f"tv_hud-cli={cli_bin}"]
        play_url = file_path
        fifo_fd = None
        if live_dump:
            opened = Timeshift.picture_open_byte()
            follow_pid = Timeshift.start_follow(opened)
            if not follow_pid:
                return False
            fifo_fd = _open_follow_reader(FOLLOW_FIFO_PATH, follow_pid)
            if fifo_fd is None:
                Timeshift.stop_follow()
                return False
            stdin = fifo_fd
            # One read end. A path open also runs the disc probes, and those
            # steal the first bytes, so the picture never locks.
            play_url = "fd://0"
            script_opts.append(f"tv_hud-timeshift-file={file_path}")
            script_opts.append(f"tv_hud-follow-sock={FOLLOW_SOCKET_PATH}")
            if channel:
                script_opts.append("tv_hud-tune=" + channel.replace(",", " "))
            cmd.extend([
                "--demuxer=lavf",
                "--demuxer-lavf-format=mpegts",
                "--keep-open=yes",
                "--keep-open-pause=no",
                "--cache-pause=no",
                "--cache=no",
                "--demuxer-readahead-secs=3",
                "--demuxer-max-bytes=4194304",
                # Under a second of the whole tower. Every station's tracks are in it;
                # the 5 MB default only waits longer for the same picture.
                "--demuxer-lavf-probesize=2000000",
                "--ytdl=no",
            ])
        else:
            cmd.append("--force-seekable=yes")
        Timeshift.ensure_dir()
        log_path = os.path.join(TIMESHIFT_DIR, "hud.log")
        touch_private_file(log_path)
        cmd.append(f"--log-file={log_path}")
        cmd.append("--script-opts=" + ",".join(script_opts))
        cmd.append(play_url)
        self.proc = subprocess.Popen(
            own_scope(cmd, slice_name=LIVE_SLICE),
            stdin=stdin,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        if fifo_fd is not None:
            os.close(fifo_fd)
        chmod_private_file(log_path)
        def commit_playing() -> bool:
            if live_dump:
                label = channel or Timeshift.current_channel() or os.path.basename(file_path)
                st = station or ""
                play_mode = mode or "live"
            else:
                label = channel or os.path.splitext(os.path.basename(file_path))[0].replace("_", " ")
                st = station or "Recording"
                play_mode = mode or "recording"
            update_player_state(
                True,
                channel=label,
                station=st,
                pid=self.proc.pid if self.proc else 0,
                mode=play_mode,
            )
            if live_dump:
                self.send_command(["set_property", "pause", False])
                Timeshift.patch_state(
                    view="live",
                    paused=False,
                    playhead_byte=opened,
                    live_lag=0,
                )
            return True

        deadline = time.time() + LAUNCH_SOCKET_WAIT_SECS
        while time.time() < deadline:
            if self.proc is not None and isinstance(self.proc.poll(), int):
                return False
            if os.path.exists(self.socket_path):
                time.sleep(0.1)
                return commit_playing()
            time.sleep(0.05)
        if self.proc is not None and self.proc.poll() is None:
            return commit_playing()
        return False

    def playback_mode(self) -> Optional[str]:
        """Returns 'live', 'file', or None when MPV is not running."""
        if not self.is_running():
            return None
        res = self.send_command(["get_property", "path"])
        path = res.get("data") if res and res.get("error") == "success" else None
        if is_timeshift_path(path) or is_follow_path(path) or is_dvb_path(path):
            return "live"
        if isinstance(path, str) and path.strip():
            return "file"
        if Timeshift.current_channel():
            return "live"
        return "live"

    def return_to_live(self, channel_name: Optional[str] = None) -> bool:
        """Seek the dump write head in this window, or retune after a library file."""
        path = self._mpv_path()
        named = (channel_name or "").strip()
        if named and not (is_timeshift_path(path) or is_follow_path(path)):
            Timeshift.wipe()
            return self.tune(named)
        if is_timeshift_path(path) or is_follow_path(path):
            if named:
                return self.tune(named)
            return self.transport.seek_cursor(Timeshift.live_join_byte(), paused=False)
        Timeshift.wipe()
        target = named or load_last_live_channel()
        if not target:
            self.channels = self._load_channels()
            if self.channels:
                target = str(self.channels[0].get("tune_name") or self.channels[0].get("name") or "")
        if not target:
            return False
        return self.tune(target)

    def get_active_channel_name(self) -> Optional[str]:
        """Queries running MPV for the live station (dump file or leftover dvb://)."""
        res = self.send_command(["get_property", "path"])
        if res and res.get("error") == "success":
            path = res.get("data")
            if is_timeshift_path(path) or is_follow_path(path):
                return Timeshift.current_channel() or load_last_live_channel() or None
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
            channel_filter=str(prefs.get("channel_filter") or "favorites"),
            hidden=load_hidden(),
        )
        if not pool:
            return
        found = find_channel_index(pool, self.get_active_channel_name())
        if found is None:
            found = find_channel_index(pool, load_last_live_channel())
        if found is None:
            next_idx = 0 if delta > 0 else len(pool) - 1
        else:
            next_idx = (found + delta) % len(pool)
        self.current_channel_index = next_idx
        ch = pool[next_idx]
        self.tune(ch.get("tune_name") or ch.get("name", ""))

    def _mpv_path(self) -> Optional[str]:
        res = self.send_command(["get_property", "path"])
        return res.get("data") if res and res.get("error") == "success" else None

    def _load_dump(self, url: str) -> None:
        """Open the dump. The HUD picks this station's tracks once it loads."""
        self.send_command(["loadfile", url, "replace"])

    def open_timeshift_dump(self, byte: int, paused: bool) -> bool:
        return self.transport.open_dump(byte, paused)

    def toggle_pause(self) -> None:
        self.transport.toggle_pause()

    def seek(self, seconds: float) -> bool:
        return self.transport.seek(seconds)

    def toggle_fullscreen(self, target_tv: bool = False) -> None:
        """Omarchy Super+F dispatcher. Unpin this PiP first — Hyprland no-ops fullscreen while pinned."""
        _toggle_omarchy_fullscreen(target_tv=target_tv)

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

    def stop(self) -> None:
        """Close TV. The live slice holds the window, dump, and follower, so nothing outlives it."""
        if self.is_running():
            self.send_command(["quit"])
        self._wait_until_stopped()
        Timeshift.wipe()
        if not in_unit(LIVE_SLICE):
            stop_unit(LIVE_SLICE)
        update_player_state(False)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _wait_while(still, timeout: float) -> bool:
    """True once `still()` is false. False if it stays true through the timeout."""
    deadline = time.time() + max(0.0, float(timeout))
    while still():
        if time.time() >= deadline:
            return False
        time.sleep(0.05)
    return True


def reap_after_exit(pid: int, pid_wait: float = 8.0, lock_wait: float = 90.0) -> bool:
    """After this window pid is gone and no tune holds the lock, reconcile.

    True means the dump was kept: the window was still alive, a tune was
    still locking, or a player is up. False means the pause file was deleted.
    """
    if not _wait_while(lambda: _pid_alive(pid), pid_wait):
        return True
    if not _wait_while(Timeshift.tune_lock_held, lock_wait):
        return True
    return MpvController().reconcile()


def _detach_stdio() -> None:
    try:
        fd = os.open(os.devnull, os.O_RDWR)
    except OSError:
        return
    try:
        os.dup2(fd, 0)
        os.dup2(fd, 1)
        os.dup2(fd, 2)
    finally:
        if fd > 2:
            os.close(fd)


def spawn_reap(pid: int) -> None:
    """Leave the closing window's process and reap once that pid is dead.

    The parent returns immediately. Super+W runs this from inside mpv, so
    waiting here would sit on the process that has to exit.
    """
    if pid <= 1:
        return
    try:
        if os.fork() > 0:
            return
    except OSError:
        return
    try:
        os.setsid()
        if os.fork() > 0:
            os._exit(0)
    except OSError:
        os._exit(1)
    try:
        os.chdir("/")
        _detach_stdio()
        reap_after_exit(pid)
    finally:
        os._exit(0)


if __name__ == "__main__":
    controller = MpvController()
    print("MPV Running:", controller.is_running())
