"""
Throwaway pause-live buffer: dump Tuner 0 to a growing MPEG-TS file.

A follow process copies live.ts to stdout and waits at EOF. Windowed MPV
reads that pipe. Pause stops the reader; skip is SEEK on the follow socket.
Return-to-live is the write head. This is not a library recording and not
dvb:// cache.
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
    TIMESHIFT_SOCKET_PATH,
    TUNE_LOCK_PATH,
)

FOLLOW_TS_PY = os.path.join(os.path.dirname(os.path.realpath(__file__)), "follow_ts.py")

# Same floor as library dumps: PAT/PMT-only is not a picture.
MIN_PLAYABLE_BYTES = 256 * 1024
# ATSC lock plus PAT/PMT can exceed a few seconds. Do not kill a dump that is
# still writing just because this floor is not hit yet.
DUMP_WAIT_SECS = 20.0
DUMP_GROWING_BYTES = 32 * 1024


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
    def acquire_tune_lock(cls) -> None:
        """Marks an in-flight retune so sync/Cmd+W cannot wipe the new dump."""
        tmp = f"{TUNE_LOCK_PATH}.tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
        os.replace(tmp, TUNE_LOCK_PATH)

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
    def stop_dump(cls) -> None:
        state = cls.load_state()
        pid = int(state.get("pid") or 0)
        sock = str(state.get("socket") or TIMESHIFT_SOCKET_PATH)
        if os.path.exists(sock):
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.settimeout(1.0)
                    s.connect(sock)
                    s.sendall(b'{"command": ["quit"]}\n')
            except OSError:
                pass
        if cls._pid_alive(pid):
            deadline = time.time() + 2.0
            while time.time() < deadline and cls._pid_alive(pid):
                time.sleep(0.05)
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
    def send_follow_seek(cls, byte_offset: int) -> bool:
        sock = str(cls.load_state().get("follow_socket") or FOLLOW_SOCKET_PATH)
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(1.0)
                s.connect(sock)
                s.sendall(f"SEEK {max(0, int(byte_offset))}\n".encode("utf-8"))
            return True
        except OSError:
            return False

    @classmethod
    def wipe(cls) -> None:
        cls.stop_follow()
        cls.stop_dump()
        cls._remove_files()

    @classmethod
    def _wait_frontend_free(cls, timeout: float = 2.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            busy = False
            for adapter_id in (0, 1):
                path = f"/dev/dvb/adapter{adapter_id}/frontend0"
                if not os.path.exists(path):
                    continue
                try:
                    res = subprocess.run(
                        ["fuser", path],
                        capture_output=True,
                        timeout=1,
                    )
                    if res.returncode == 0:
                        busy = True
                        break
                except Exception:
                    return
            if not busy:
                return
            time.sleep(0.05)

    @classmethod
    def start_dump(cls, tune_name: str, adapter_id: Optional[int] = None) -> Optional[str]:
        """Locks a tuner, dumps dvb:// into live.ts, waits until the file is playable."""
        from engine.tuner import TunerManager

        name = (tune_name or "").strip()
        if not name:
            return None

        cls.wipe()
        cls.ensure_dir()
        cls._wait_frontend_free(timeout=2.0)

        if adapter_id is None:
            available = TunerManager.get_available_tuner(require_atsc=True)
            adapter_id = available.adapter_id if available else 0

        sock = TIMESHIFT_SOCKET_PATH
        if os.path.exists(sock):
            try:
                os.unlink(sock)
            except OSError:
                pass

        cmd = [
            "mpv",
            f"--stream-dump={TIMESHIFT_FILE}",
            "--vo=null",
            "--ao=null",
            "--cache=yes",
            f"--input-ipc-server={sock}",
            f"--dvbin-card={adapter_id}",
            f"--dvbin-file={MPV_CHANNELS_CONF}",
            "--idle=no",
            f"dvb://{name}",
        ]
        log_path = os.path.join(TIMESHIFT_DIR, "dump.log")
        log_file = open(log_path, "ab")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=log_file,
            start_new_session=True,
        )
        try:
            log_file.close()
        except OSError:
            pass
        if isinstance(proc.poll(), int):
            cls._clear_state()
            return None

        cls._write_state({
            "running": True,
            "channel": name,
            "tune_name": name,
            "adapter_id": adapter_id,
            "path": TIMESHIFT_FILE,
            "pid": proc.pid,
            "socket": sock,
            "updated_at": time.time(),
        })

        deadline = time.time() + DUMP_WAIT_SECS
        last_size = 0
        while time.time() < deadline:
            if isinstance(proc.poll(), int):
                cls.stop_dump()
                return None
            try:
                size = os.path.getsize(TIMESHIFT_FILE) if os.path.isfile(TIMESHIFT_FILE) else 0
            except OSError:
                size = 0
            if size >= MIN_PLAYABLE_BYTES:
                return TIMESHIFT_FILE
            last_size = size
            time.sleep(0.05)

        if cls._pid_alive(proc.pid) and last_size >= DUMP_GROWING_BYTES:
            return TIMESHIFT_FILE
        cls.stop_dump()
        return None
