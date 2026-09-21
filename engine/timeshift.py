"""
Throwaway pause-live buffer: dump Tuner 0 to a growing MPEG-TS file.

A follow process copies live.ts to stdout and waits at EOF. Windowed MPV
reads that pipe while live. Delayed pause/skip `loadfile`s the dump
(start=# byte). Last skip toward live, or `l`, remaps the follow pipe.
Channel change fills the new dump, then `pip-relaunch` (new session) remaps
the PiP. HUD `omarchy-tv play` must not quit mpv itself — that child dies
with the window. Return-to-live is the write head. This is not a library
recording and not dvb:// cache.
"""

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from typing import Any, Dict, Optional

from engine.paths import (
    FOLLOW_SOCKET_PATH,
    MPV_CHANNELS_CONF,
    TIMESHIFT_ACTIVE_PATH,
    TIMESHIFT_DIR,
    TIMESHIFT_FILE,
    TIMESHIFT_NEXT_FILE,
    TIMESHIFT_NEXT_SOCKET_PATH,
    TIMESHIFT_SOCKET_PATH,
    TUNE_LOCK_PATH,
)

FOLLOW_TS_PY = os.path.join(os.path.dirname(os.path.realpath(__file__)), "follow_ts.py")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

# Same floor as library dumps: PAT/PMT-only is not a picture.
MIN_PLAYABLE_BYTES = 256 * 1024
# ATSC lock plus PAT/PMT can exceed a few seconds. Do not kill a dump that is
# still writing just because this floor is not hit yet.
DUMP_WAIT_SECS = 20.0
DUMP_GROWING_BYTES = 32 * 1024


TS_PACKET = 188
ATSC_BPS = 19_390_000
SEEK_STEP = 10.0
SEEK_NEAR = 5.0
LIVE_SLACK = 2.5


def align_ts(n: int) -> int:
    n = max(0, int(n or 0))
    return n - (n % TS_PACKET)


def is_timeshift_path(file_path: Optional[str]) -> bool:
    if not file_path or str(file_path).strip().lower().startswith("dvb://"):
        return False
    try:
        real = os.path.realpath(file_path)
        root = os.path.realpath(TIMESHIFT_DIR)
        return os.path.commonpath([root, real]) == root
    except (ValueError, OSError):
        return False


class Timeshift:
    @classmethod
    def acquire_tune_lock(cls) -> bool:
        """Marks an in-flight retune so sync/Cmd+W cannot wipe the new dump.

        Returns False if another living process already holds the lock (stacked j/k).
        """
        if cls.tune_lock_held():
            return False
        tmp = f"{TUNE_LOCK_PATH}.tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        os.replace(tmp, TUNE_LOCK_PATH)
        return True

    @classmethod
    def tune_lock_held(cls) -> bool:
        try:
            with open(TUNE_LOCK_PATH, "r", encoding="utf-8") as f:
                pid = int((f.read() or "0").strip() or 0)
        except (OSError, ValueError):
            return False
        if cls._pid_alive(pid):
            return True
        try:
            os.unlink(TUNE_LOCK_PATH)
        except OSError:
            pass
        return False

    @classmethod
    def release_tune_lock(cls) -> None:
        try:
            with open(TUNE_LOCK_PATH, "r", encoding="utf-8") as f:
                pid = int((f.read() or "0").strip() or 0)
        except (OSError, ValueError):
            return
        if pid != os.getpid():
            return
        try:
            os.unlink(TUNE_LOCK_PATH)
        except OSError:
            pass

    @classmethod
    def ensure_dir(cls) -> str:
        os.makedirs(TIMESHIFT_DIR, mode=0o755, exist_ok=True)
        return TIMESHIFT_DIR

    @classmethod
    def dump_path(cls) -> str:
        return TIMESHIFT_FILE

    @classmethod
    def patch_state(cls, **fields: Any) -> None:
        state = cls.load_state()
        state.update(fields)
        state["updated_at"] = time.time()
        cls._write_state(state)

    @classmethod
    def dump_bytes(cls) -> int:
        try:
            return int(os.path.getsize(TIMESHIFT_FILE))
        except OSError:
            return 0

    @classmethod
    def live_edge_byte(cls) -> int:
        size = cls.dump_bytes()
        if size <= TS_PACKET:
            return 0
        return align_ts(size - TS_PACKET)

    @classmethod
    def _http_port_up(cls, port: int) -> bool:
        if port <= 0:
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return True
        except OSError:
            return False

    @classmethod
    def start_http(cls) -> int:
        """Loopback MPEG-TS server in its own process. The play CLI must not own it."""
        state = cls.load_state()
        pid = int(state.get("http_pid") or 0)
        port = int(state.get("http_port") or 0)
        if pid > 0 and port > 0 and cls._pid_alive(pid) and cls._http_port_up(port):
            return port
        cls.stop_http()
        proc = subprocess.Popen(
            [sys.executable, "-m", "engine.timeshift_http", TIMESHIFT_FILE],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            cwd=PROJECT_ROOT,
        )
        if proc.stdout is None:
            cls._kill_pid(proc.pid)
            return 0
        line = proc.stdout.readline()
        try:
            proc.stdout.close()
        except OSError:
            pass
        if isinstance(proc.poll(), int):
            return 0
        try:
            port = int(line.strip())
        except (TypeError, ValueError):
            cls._kill_pid(proc.pid)
            return 0
        cls.patch_state(http_port=port, http_pid=proc.pid)
        return port

    @classmethod
    def stop_http(cls) -> None:
        state = cls.load_state()
        pid = int(state.get("http_pid") or 0)
        cls._kill_pid(pid)
        if state:
            state.pop("http_port", None)
            state.pop("http_pid", None)
            state["updated_at"] = time.time()
            cls._write_state(state)

    @classmethod
    def http_url(cls, start_byte: int = 0) -> str:
        port = int(cls.load_state().get("http_port") or 0)
        if port <= 0:
            port = cls.start_http()
        return f"http://127.0.0.1:{port}/live.ts?from={align_ts(start_byte)}"

    @classmethod
    def write_rate(cls) -> float:
        """Bytes/sec of the dump. Pause growth first, else last measure, else ATSC."""
        state = cls.load_state()
        try:
            t0 = float(state.get("playhead_t") or 0)
        except (TypeError, ValueError):
            t0 = 0.0
        held = time.time() - t0 if t0 > 0 else 0.0
        playhead = int(state.get("playhead_byte") or 0)
        if bool(state.get("paused")) and held > 0.5:
            return max(1000.0, (cls.dump_bytes() - playhead) / held)
        try:
            bps = float(state.get("mux_bps") or 0)
        except (TypeError, ValueError):
            bps = 0.0
        if bps >= 1000:
            return bps
        return ATSC_BPS / 8.0

    @classmethod
    def delay_sec(cls) -> float:
        state = cls.load_state()
        if str(state.get("view") or "live") == "live" and not bool(state.get("paused")):
            return 0.0
        if bool(state.get("paused")):
            try:
                t0 = float(state.get("playhead_t") or 0)
            except (TypeError, ValueError):
                t0 = 0.0
            if t0 > 0:
                return max(0.0, time.time() - t0)
        rate = cls.write_rate()
        if rate <= 0:
            return 0.0
        return max(0.0, (cls.dump_bytes() - cls.playhead_now()) / rate)

    @classmethod
    def mux_rate(cls) -> float:
        return cls.write_rate()

    @classmethod
    def follow_pos(cls) -> Optional[int]:
        sock = str(cls.load_state().get("follow_socket") or FOLLOW_SOCKET_PATH)
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                s.connect(sock)
                s.sendall(b"POS")
                s.shutdown(socket.SHUT_WR)
                data = (s.recv(64) or b"").decode("utf-8", "replace").strip()
            return align_ts(int(data))
        except (OSError, ValueError):
            return None

    @classmethod
    def playhead_now(cls) -> int:
        state = cls.load_state()
        pos = int(state.get("playhead_byte") or 0)
        view = str(state.get("view") or "live")
        paused = bool(state.get("paused"))
        if view == "delayed" and not paused:
            try:
                t0 = float(state.get("playhead_t") or 0)
            except (TypeError, ValueError):
                t0 = 0.0
            if t0 > 0:
                pos += int((time.time() - t0) * cls.mux_rate())
        size = cls.dump_bytes()
        if size > TS_PACKET:
            pos = min(pos, size - TS_PACKET)
        return align_ts(max(0, pos))

    @classmethod
    def remain_sec(cls) -> float:
        rate = cls.mux_rate()
        if rate <= 0:
            return 0.0
        return max(0.0, (cls.dump_bytes() - cls.playhead_now()) / rate)

    @classmethod
    def fwd_hop(cls, remain: float) -> float:
        if remain <= LIVE_SLACK:
            return 0.0
        if remain <= (SEEK_NEAR + LIVE_SLACK):
            return remain
        if remain <= (SEEK_STEP * 2):
            return SEEK_NEAR
        return SEEK_STEP

    @classmethod
    def load_state(cls) -> Dict[str, Any]:
        try:
            if os.path.exists(TIMESHIFT_ACTIVE_PATH):
                with open(TIMESHIFT_ACTIVE_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
        except Exception:
            pass
        return {}

    @classmethod
    def current_channel(cls) -> str:
        state = cls.load_state()
        if not state.get("running"):
            return ""
        return str(state.get("tune_name") or state.get("channel") or "").strip()

    @classmethod
    def _write_state(cls, payload: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(TIMESHIFT_ACTIVE_PATH), exist_ok=True)
        tmp = f"{TIMESHIFT_ACTIVE_PATH}.tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, TIMESHIFT_ACTIVE_PATH)

    @classmethod
    def _clear_state(cls) -> None:
        cls._write_state({"running": False, "updated_at": time.time()})

    @classmethod
    def _pid_alive(cls, pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    @classmethod
    def stop_dump(cls, keep_follow: bool = False) -> None:
        state = cls.load_state()
        pid = int(state.get("pid") or 0)
        sock = str(state.get("socket") or TIMESHIFT_SOCKET_PATH)
        follow_pid = int(state.get("follow_pid") or 0) if keep_follow else 0
        follow_socket = str(state.get("follow_socket") or FOLLOW_SOCKET_PATH) if keep_follow else ""
        if os.path.exists(sock):
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.settimeout(0.3)
                    s.connect(sock)
                    s.sendall(b'{"command": ["quit"]}\n')
            except OSError:
                pass
        if cls._pid_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
            deadline = time.time() + 0.4
            while time.time() < deadline and cls._pid_alive(pid):
                time.sleep(0.02)
            if cls._pid_alive(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
                deadline = time.time() + 0.3
                while time.time() < deadline and cls._pid_alive(pid):
                    time.sleep(0.02)
        if os.path.exists(sock):
            try:
                os.unlink(sock)
            except OSError:
                pass
        if keep_follow:
            cls._write_state({
                "running": False,
                "follow_pid": follow_pid,
                "follow_socket": follow_socket,
                "updated_at": time.time(),
            })
        else:
            cls._clear_state()

    @classmethod
    def _remove_files(cls) -> None:
        try:
            if not os.path.isdir(TIMESHIFT_DIR):
                return
            for name in os.listdir(TIMESHIFT_DIR):
                if name == "dump.log" or name == "hud.log":
                    continue
                path = os.path.join(TIMESHIFT_DIR, name)
                try:
                    if os.path.isdir(path):
                        shutil.rmtree(path, ignore_errors=True)
                    elif os.path.isfile(path) or os.path.islink(path):
                        os.remove(path)
                except OSError:
                    pass
        except OSError:
            pass

    @classmethod
    def stop_follow(cls) -> None:
        state = cls.load_state()
        pid = int(state.get("follow_pid") or 0)
        sock = str(state.get("follow_socket") or FOLLOW_SOCKET_PATH)
        if cls._pid_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
            deadline = time.time() + 1.0
            while time.time() < deadline and cls._pid_alive(pid):
                time.sleep(0.05)
            if cls._pid_alive(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
        if os.path.exists(sock):
            try:
                os.unlink(sock)
            except OSError:
                pass
        if state:
            state.pop("follow_pid", None)
            state.pop("follow_socket", None)
            state["updated_at"] = time.time()
            cls._write_state(state)

    @classmethod
    def start_follow(cls, start_byte: int = 0) -> Optional[subprocess.Popen]:
        """Stdout is a never-EOF MPEG-TS pipe of live.ts for the windowed player."""
        cls.stop_follow()
        sock = FOLLOW_SOCKET_PATH
        if os.path.exists(sock):
            try:
                os.unlink(sock)
            except OSError:
                pass
        proc = subprocess.Popen(
            [
                sys.executable,
                FOLLOW_TS_PY,
                TIMESHIFT_FILE,
                str(max(0, int(start_byte))),
                sock,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        if isinstance(proc.poll(), int):
            return None
        state = cls.load_state()
        state["follow_pid"] = proc.pid
        state["follow_socket"] = sock
        state["updated_at"] = time.time()
        cls._write_state(state)
        return proc

    @classmethod
    def send_follow_cmd(cls, line: str) -> bool:
        sock = str(cls.load_state().get("follow_socket") or FOLLOW_SOCKET_PATH)
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                s.connect(sock)
                s.sendall((line.strip() + "\n").encode("utf-8"))
            return True
        except OSError:
            return False

    @classmethod
    def send_follow_seek(cls, byte_offset: int) -> bool:
        return cls.send_follow_cmd(f"SEEK {max(0, int(byte_offset))}")

    @classmethod
    def send_follow_pause(cls) -> bool:
        return cls.send_follow_cmd("PAUSE")

    @classmethod
    def send_follow_play(cls) -> bool:
        return cls.send_follow_cmd("PLAY")

    @classmethod
    def send_follow_pace(cls, bytes_per_sec: float = 0) -> bool:
        if bytes_per_sec and bytes_per_sec >= 1000:
            return cls.send_follow_cmd(f"PACE {int(bytes_per_sec)}")
        return cls.send_follow_cmd("PACE")

    @classmethod
    def send_follow_catchup(cls) -> bool:
        return cls.send_follow_cmd("CATCHUP")

    @classmethod
    def send_follow_reopen(cls) -> bool:
        return cls.send_follow_cmd("REOPEN")

    @classmethod
    def wipe(cls) -> None:
        cls.stop_http()
        cls.stop_follow()
        cls.stop_dump()
        cls._reap_orphan_dumps()
        cls._remove_files()

    @classmethod
    def _reap_orphan_dumps(cls, keep_pid: int = 0) -> None:
        """Kills leftover stream-dump mpv that state no longer tracks (stacked surf)."""
        try:
            out = subprocess.check_output(
                ["pgrep", "-a", "mpv"],
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except Exception:
            return
        for line in out.splitlines():
            if "--stream-dump=" not in line or "omarchy/tv/timeshift/" not in line:
                continue
            try:
                pid = int(line.split(None, 1)[0])
            except ValueError:
                continue
            if pid <= 1 or pid == keep_pid:
                continue
            cls._kill_pid(pid)

    @classmethod
    def _wait_frontend_free(cls, timeout: float = 0.6, adapter_id: Optional[int] = None) -> None:
        adapters = (adapter_id,) if adapter_id is not None else (0, 1)
        deadline = time.time() + timeout
        while time.time() < deadline:
            busy = False
            for aid in adapters:
                path = f"/dev/dvb/adapter{aid}/frontend0"
                if not os.path.exists(path):
                    continue
                try:
                    res = subprocess.run(
                        ["fuser", path],
                        capture_output=True,
                        timeout=0.4,
                    )
                    if res.returncode == 0:
                        busy = True
                        break
                except Exception:
                    return
            if not busy:
                return
            time.sleep(0.03)

    @classmethod
    def _spawn_dump(
        cls,
        name: str,
        adapter_id: int,
        dest: str,
        sock: str,
        log_name: str = "dump.log",
    ) -> Optional[subprocess.Popen]:
        if os.path.exists(sock):
            try:
                os.unlink(sock)
            except OSError:
                pass
        cmd = [
            "mpv",
            f"--stream-dump={dest}",
            "--vo=null",
            "--ao=null",
            "--cache=yes",
            f"--input-ipc-server={sock}",
            f"--dvbin-card={adapter_id}",
            f"--dvbin-file={MPV_CHANNELS_CONF}",
            "--idle=no",
            f"--log-file={os.path.join(TIMESHIFT_DIR, log_name)}",
            f"dvb://{name}",
        ]
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        if isinstance(proc.poll(), int):
            return None
        return proc

    @classmethod
    def _wait_dump_playable(cls, proc: subprocess.Popen, dest: str) -> bool:
        deadline = time.time() + DUMP_WAIT_SECS
        last_size = 0
        while time.time() < deadline:
            if isinstance(proc.poll(), int):
                return False
            try:
                size = os.path.getsize(dest) if os.path.isfile(dest) else 0
            except OSError:
                size = 0
            if size >= MIN_PLAYABLE_BYTES:
                return True
            last_size = size
            time.sleep(0.05)
        return cls._pid_alive(proc.pid) and last_size >= DUMP_GROWING_BYTES

    @classmethod
    def _kill_pid(cls, pid: int) -> None:
        if pid <= 0:
            return
        if cls._pid_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
            deadline = time.time() + 0.4
            while time.time() < deadline and cls._pid_alive(pid):
                time.sleep(0.02)
            if cls._pid_alive(pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
        deadline = time.time() + 0.4
        while time.time() < deadline:
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                return
            if not cls._pid_alive(pid):
                return
            time.sleep(0.02)

    @classmethod
    def start_dump(
        cls,
        tune_name: str,
        adapter_id: Optional[int] = None,
        keep_follow: bool = False,
    ) -> Optional[str]:
        """Locks a tuner, dumps dvb:// into live.ts, waits until the file is playable.

        keep_follow: channel change under a live PiP. Stop the dump, replace
        live.ts, and leave the follow pid in state. The player then recycles
        the PiP onto a new follow pipe so lavf starts the new mux.
        """
        from engine.tuner import TunerManager

        name = (tune_name or "").strip()
        if not name:
            return None

        follow_pid = 0
        follow_socket = FOLLOW_SOCKET_PATH
        if keep_follow:
            state = cls.load_state()
            follow_pid = int(state.get("follow_pid") or 0)
            follow_socket = str(state.get("follow_socket") or FOLLOW_SOCKET_PATH)
            cls.stop_dump(keep_follow=True)
            try:
                if os.path.isfile(TIMESHIFT_FILE):
                    os.remove(TIMESHIFT_FILE)
            except OSError:
                pass
            cls.ensure_dir()
        else:
            cls.wipe()
            cls.ensure_dir()

        if adapter_id is None:
            available = TunerManager.get_available_tuner(require_atsc=True)
            adapter_id = available.adapter_id if available else 0

        cls._reap_orphan_dumps()
        cls._wait_frontend_free(timeout=0.8, adapter_id=adapter_id)
        sock = TIMESHIFT_SOCKET_PATH
        proc = cls._spawn_dump(name, adapter_id, TIMESHIFT_FILE, sock)
        if proc is None:
            if keep_follow:
                cls._write_state({
                    "running": False,
                    "follow_pid": follow_pid,
                    "follow_socket": follow_socket,
                    "updated_at": time.time(),
                })
            else:
                cls._clear_state()
            return None

        payload = {
            "running": True,
            "channel": name,
            "tune_name": name,
            "adapter_id": adapter_id,
            "path": TIMESHIFT_FILE,
            "pid": proc.pid,
            "socket": sock,
            "view": "live",
            "paused": False,
            "playhead_byte": 0,
            "playhead_t": 0,
            "updated_at": time.time(),
        }
        if keep_follow and follow_pid:
            payload["follow_pid"] = follow_pid
            payload["follow_socket"] = follow_socket
        cls._write_state(payload)

        if cls._wait_dump_playable(proc, TIMESHIFT_FILE):
            return TIMESHIFT_FILE
        cls.stop_dump(keep_follow=keep_follow)
        return None

    @classmethod
    def retune_keep_window(cls, tune_name: str) -> Optional[str]:
        """Swap live.ts to a new station without killing the follow/PiP.

        If Tuner 1 is free, lock the next station there while the current
        dump keeps filling (picture keeps moving), then cut over. If not,
        pause the follower and retune Tuner 0.
        """
        from engine.tuner import TunerManager

        name = (tune_name or "").strip()
        if not name:
            return None
        state = cls.load_state()
        follow_pid = int(state.get("follow_pid") or 0)
        follow_socket = str(state.get("follow_socket") or FOLLOW_SOCKET_PATH)
        current_adapter = int(state.get("adapter_id") or 0)
        other = TunerManager.get_available_tuner(
            require_atsc=True,
            exclude_adapters={current_adapter},
        )
        if other is not None:
            cls.ensure_dir()
            try:
                if os.path.isfile(TIMESHIFT_NEXT_FILE):
                    os.remove(TIMESHIFT_NEXT_FILE)
            except OSError:
                pass
            live_sock = str(state.get("socket") or TIMESHIFT_SOCKET_PATH)
            next_sock = (
                TIMESHIFT_SOCKET_PATH
                if live_sock == TIMESHIFT_NEXT_SOCKET_PATH
                else TIMESHIFT_NEXT_SOCKET_PATH
            )
            proc = cls._spawn_dump(
                name,
                other.adapter_id,
                TIMESHIFT_NEXT_FILE,
                next_sock,
                log_name="dump-next.log",
            )
            if proc is not None and cls._wait_dump_playable(proc, TIMESHIFT_NEXT_FILE):
                cls.stop_dump(keep_follow=True)
                cls._reap_orphan_dumps(keep_pid=proc.pid)
                try:
                    os.replace(TIMESHIFT_NEXT_FILE, TIMESHIFT_FILE)
                except OSError:
                    cls._kill_pid(proc.pid)
                    proc = None
                else:
                    cls._write_state({
                        "running": True,
                        "channel": name,
                        "tune_name": name,
                        "adapter_id": other.adapter_id,
                        "path": TIMESHIFT_FILE,
                        "pid": proc.pid,
                        "socket": next_sock,
                        "follow_pid": follow_pid,
                        "follow_socket": follow_socket,
                        "view": "live",
                        "paused": False,
                        "playhead_byte": 0,
                        "playhead_t": 0,
                        "updated_at": time.time(),
                    })
                    return TIMESHIFT_FILE
            if proc is not None:
                cls._kill_pid(proc.pid)
            try:
                if os.path.isfile(TIMESHIFT_NEXT_FILE):
                    os.remove(TIMESHIFT_NEXT_FILE)
            except OSError:
                pass

        cls.send_follow_pause()
        return cls.start_dump(name, keep_follow=True)
