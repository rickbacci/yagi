"""
Omarchy TV - Dual-Tuner DVR & Recording Engine
Handles background ATSC broadcast recording, hardware tuner leasing,
active recording tracking, and file lifecycle management.
"""

import os
import re
import json
import time
import socket
import signal
import threading
import subprocess
import shutil
from datetime import datetime
from typing import List, Dict, Optional, Any, Set

from engine.paths import (
    CHANNELS_JSON_PATH,
    MPV_CHANNELS_CONF,
    RECORDINGS_DIR,
    RECORDINGS_ACTIVE_PATH,
    RECORDINGS_INDEX_PATH,
    UI_PREFS_PATH,
    chmod_private_file,
    ensure_private_dir,
    TUNER1_LOCK_KEY,
    get_runtime_socket,
    own_scope,
    state_lock,
    touch_private_file,
)
from engine.tuner import TunerManager, WORK_ADAPTER
from engine.enrichment import match_channel
from engine.guide import current_program_title, get_channel_program, load_guide


def format_bytes(bytes_count: int) -> str:
    """Format byte count into human-readable string (e.g. 142.5 MB)."""
    if bytes_count < 1024:
        return f"{bytes_count} B"
    elif bytes_count < 1024 * 1024:
        return f"{bytes_count / 1024:.1f} KB"
    elif bytes_count < 1024 * 1024 * 1024:
        return f"{bytes_count / (1024 * 1024):.1f} MB"
    else:
        return f"{bytes_count / (1024 * 1024 * 1024):.2f} GB"


# PAT/PMT-only dumps are ~4 KB. Real ATSC MPEG-TS grows by megabytes per second.
MIN_PLAYABLE_BYTES = 256 * 1024
GIB = 1024 ** 3
DEFAULT_LIBRARY_BUDGET_GIB = 20
MIN_LIBRARY_BUDGET_GIB = 2
KEEP_FREE_GIB = 8
# A locked ATSC dump passes this quickly. PAT/PMT alone does not.
GROW_BYTES = 32 * 1024
GROW_WAIT_SECS = 20.0
# One Guide tower can hold Tuner 1 this long before it lets go.
TUNER1_WAIT_SECS = 30.0
FRONTEND_SETTLE_SECS = 3.0
# A file written this recently may still be recording. Budget pruning leaves it.
PRUNE_QUIET_SECS = 120


def load_ui_prefs(prefs_path: Optional[str] = None) -> Dict[str, Any]:
    target = prefs_path or UI_PREFS_PATH
    if os.path.exists(target):
        try:
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}


def default_library_budget_bytes(recordings_dir: str) -> int:
    """Small starting cap: 20 GB, shrunk when the volume is tight."""
    try:
        ensure_private_dir(recordings_dir)
        usage = shutil.disk_usage(recordings_dir)
    except OSError:
        return DEFAULT_LIBRARY_BUDGET_GIB * GIB
    small = DEFAULT_LIBRARY_BUDGET_GIB * GIB
    volume_cap = max(MIN_LIBRARY_BUDGET_GIB * GIB, int(usage.total * 0.15))
    keep_free = KEEP_FREE_GIB * GIB
    if usage.free < keep_free + MIN_LIBRARY_BUDGET_GIB * GIB:
        return max(GIB, int(usage.free * 0.5))
    free_cap = max(MIN_LIBRARY_BUDGET_GIB * GIB, usage.free - keep_free)
    return int(min(small, volume_cap, free_cap))


def resolve_library_budget_bytes(
    recordings_dir: Optional[str] = None,
    prefs: Optional[Dict[str, Any]] = None,
) -> Optional[int]:
    """Returns the library cap in bytes, or None when pruning is off."""
    rec_dir = recordings_dir or RECORDINGS_DIR
    prefs = prefs if prefs is not None else load_ui_prefs()
    raw = prefs.get("library_max_gb", "auto")
    if raw in (0, 0.0, "0", "off", "none", "unlimited"):
        return None
    if raw in (None, "", "auto"):
        return default_library_budget_bytes(rec_dir)
    try:
        gb = float(raw)
    except (TypeError, ValueError):
        return default_library_budget_bytes(rec_dir)
    if gb <= 0:
        return None
    return int(gb * GIB)


def sanitize_filename(name: str) -> str:
    """Sanitize string for safe cross-platform filesystem filenames."""
    clean = re.sub(r"[\\/*?:\"<>|'`’]", "", name)
    clean = re.sub(r"\s+", "_", clean).strip("._-")
    return clean or "recording"


def sidecar_path(file_path: str) -> str:
    """JSON next to the recording. The filename is no longer the only record."""
    root, _ext = os.path.splitext(file_path)
    return root + ".json"


def read_sidecar(file_path: str) -> Dict[str, Any]:
    path = sidecar_path(file_path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_sidecar(file_path: str, payload: Dict[str, Any]) -> None:
    target = sidecar_path(file_path)
    os.makedirs(os.path.dirname(os.path.abspath(target)) or ".", exist_ok=True)
    tmp = f"{target}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, target)
    chmod_private_file(target)


def patch_sidecar(file_path: str, **fields: Any) -> Dict[str, Any]:
    data = read_sidecar(file_path)
    data.update(fields)
    write_sidecar(file_path, data)
    return data


ATSC_BYTES_PER_SEC = 19_390_000 / 8


def byte_rate(size: int, start: float, end: float) -> Optional[float]:
    """Bytes a second of this file. The player turns seconds into byte seeks with it."""
    span = float(end) - float(start)
    if span < 10 or size <= 0:
        return None
    return round(size / span, 1)


def disk_below_floor(path: str) -> bool:
    """True when the volume holding path has less than the keep-free floor left."""
    try:
        free = shutil.disk_usage(path).free
    except OSError:
        return False
    return free < KEEP_FREE_GIB * GIB


def stop_reason(path: str, now: float, end_unix: Optional[float]) -> Optional[str]:
    """Why the writer should stop, or None to keep going."""
    if end_unix is not None and now >= float(end_unix):
        return "end"
    if disk_below_floor(path):
        return "disk"
    return None


class DvrSession:
    """Represents a single active or completed recording session."""

    def __init__(
        self,
        session_id: str,
        channel_number: str,
        station: str,
        tune_name: str,
        program_title: str,
        start_time: float,
        duration_seconds: Optional[int],
        adapter_id: int,
        file_path: str,
        socket_path: str,
        pid: int,
    ):
        self.session_id = session_id
        self.channel_number = channel_number
        self.station = station
        self.tune_name = tune_name
        self.program_title = program_title
        self.start_time = start_time
        self.duration_seconds = duration_seconds
        self.adapter_id = adapter_id
        self.file_path = file_path
        self.socket_path = socket_path
        self.pid = pid

    def is_active(self) -> bool:
        """Check if mpv recording process is currently alive."""
        if not self.pid:
            return False
        try:
            # Signal 0 checks if process exists without killing it
            os.kill(self.pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    def get_file_size(self) -> int:
        """Return current size on disk in bytes."""
        if os.path.exists(self.file_path):
            try:
                return os.path.getsize(self.file_path)
            except OSError:
                return 0
        return 0

    def get_elapsed_seconds(self) -> int:
        """Return elapsed recording time in seconds."""
        return max(0, int(time.time() - self.start_time))

    def stop(self, timeout: float = 3.0) -> bool:
        """Stop recording cleanly via mpv JSON-IPC, falling back to SIGTERM."""
        stopped = False
        if os.path.exists(self.socket_path):
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                    s.settimeout(1.0)
                    s.connect(self.socket_path)
                    s.sendall(b'{"command": ["quit"]}\n')
                # Wait up to timeout for process to exit
                start = time.time()
                while time.time() - start < timeout:
                    if not self.is_active():
                        stopped = True
                        break
                    time.sleep(0.1)
            except Exception:
                pass

        if not stopped and self.is_active():
            try:
                os.kill(self.pid, signal.SIGTERM)
                start = time.time()
                while time.time() - start < 1.5:
                    if not self.is_active():
                        stopped = True
                        break
                    time.sleep(0.05)
            except OSError:
                pass

        if not stopped and self.is_active():
            try:
                os.kill(self.pid, signal.SIGKILL)
                stopped = True
            except OSError:
                pass

        # Cleanup socket file if remaining
        if os.path.exists(self.socket_path):
            try:
                os.unlink(self.socket_path)
            except OSError:
                pass

        return True

    def to_dict(self) -> Dict[str, Any]:
        size = self.get_file_size()
        elapsed = self.get_elapsed_seconds()
        return {
            "session_id": self.session_id,
            "channel_number": self.channel_number,
            "station": self.station,
            "tune_name": self.tune_name,
            "program_title": self.program_title,
            "start_time": self.start_time,
            "duration_seconds": self.duration_seconds,
            "elapsed_seconds": elapsed,
            "adapter_id": self.adapter_id,
            "file_path": self.file_path,
            "socket_path": self.socket_path,
            "pid": self.pid,
            "file_size": size,
            "file_size_formatted": format_bytes(size),
            "is_active": self.is_active(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DvrSession":
        return cls(
            session_id=data.get("session_id", ""),
            channel_number=data.get("channel_number", ""),
            station=data.get("station", ""),
            tune_name=data.get("tune_name", ""),
            program_title=data.get("program_title", "Live Broadcast"),
            start_time=float(data.get("start_time", time.time())),
            duration_seconds=data.get("duration_seconds"),
            adapter_id=int(data.get("adapter_id", 0)),
            file_path=data.get("file_path", ""),
            socket_path=data.get("socket_path", ""),
            pid=int(data.get("pid", 0)),
        )


class DvrManager:
    """Manages recording sessions, scheduling, and storage."""

    @classmethod
    def load_active_sessions(cls, active_path: Optional[str] = None) -> List[DvrSession]:
        """Loads and prunes dead recording sessions."""
        target_path = active_path or RECORDINGS_ACTIVE_PATH
        if not os.path.exists(target_path):
            return []
        with state_lock(target_path):
            return cls._load_and_prune(target_path)

    @classmethod
    def _load_and_prune(cls, target_path: str) -> List[DvrSession]:
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return []

        sessions: List[DvrSession] = []
        changed = False

        for item in data:
            try:
                session = DvrSession.from_dict(item)
                if session.is_active():
                    sessions.append(session)
                else:
                    changed = True
                    cls._close_dead(session)
                    # Clean up orphaned socket
                    if os.path.exists(session.socket_path):
                        try:
                            os.unlink(session.socket_path)
                        except OSError:
                            pass
            except Exception:
                changed = True

        if changed:
            cls.save_active_sessions(sessions, target_path)

        return sessions

    @staticmethod
    def _close_dead(session: DvrSession) -> None:
        """A recorder that exited on its own. Its file is finished or failed, not still recording."""
        if not session.file_path or not os.path.exists(session.file_path):
            return
        side = read_sidecar(session.file_path)
        if str(side.get("status") or "") != "recording":
            return
        size = session.get_file_size()
        end = int(os.path.getmtime(session.file_path))
        patch_sidecar(
            session.file_path,
            status="complete" if size >= MIN_PLAYABLE_BYTES else "failed",
            end=end,
            stopped_reason="exited",
            byte_rate=byte_rate(size, session.start_time, end),
        )

    @classmethod
    def save_active_sessions(cls, sessions: List[DvrSession], active_path: Optional[str] = None) -> None:
        """Atomically saves active recording sessions to JSON."""
        target_path = active_path or RECORDINGS_ACTIVE_PATH
        os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
        tmp_path = f"{target_path}.tmp.{os.getpid()}"

        data = [s.to_dict() for s in sessions if s.is_active()]
        try:
            with state_lock(target_path):
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                os.replace(tmp_path, target_path)
        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    @classmethod
    def wait_until_growing(cls, proc: subprocess.Popen, path: str, timeout: float = GROW_WAIT_SECS) -> bool:
        """True once the dump has written a real chunk and the process is still up."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if isinstance(proc.poll(), int):
                return False
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            if size >= GROW_BYTES:
                return True
            time.sleep(0.05)
        return False

    @classmethod
    def sweep_active(cls, active_path: Optional[str] = None) -> List["DvrSession"]:
        """Stop recordings whose end has passed, or whose disk is under the floor."""
        stopped: List[DvrSession] = []
        for session in cls.load_active_sessions(active_path):
            if not session.is_active():
                continue
            side = read_sidecar(session.file_path)
            planned = side.get("planned_end")
            end_unix = None
            if planned not in (None, ""):
                try:
                    end_unix = float(planned)
                except (TypeError, ValueError):
                    end_unix = None
            if end_unix is None and session.duration_seconds:
                end_unix = float(session.start_time) + float(session.duration_seconds)
            reason = stop_reason(session.file_path, time.time(), end_unix)
            if not reason:
                continue
            if reason == "disk":
                patch_sidecar(session.file_path, stopped_reason="disk")
            cls.stop_recording(session.session_id, active_path=active_path)
            stopped.append(session)
        return stopped

    @classmethod
    def keep_pause(
        cls,
        station: str = "",
        recordings_dir: Optional[str] = None,
        state: Optional[Dict[str, Any]] = None,
        dump_path: Optional[str] = None,
    ) -> str:
        """Copy the paused span of the live dump into the library. Tuner 1 stays free."""
        from engine.timeshift import TIMESHIFT_FILE, Timeshift

        live = state if state is not None else Timeshift.load_state()
        if not live.get("running"):
            raise RuntimeError("Nothing is on.")
        tune = str(live.get("tune_name") or live.get("channel") or "").strip()
        asked = (station or "").strip()
        if asked and asked != tune:
            raise RuntimeError("That station is no longer the pause file.")
        if not tune:
            raise RuntimeError("Nothing is on.")
        source = dump_path or str(live.get("path") or "") or TIMESHIFT_FILE
        if dump_path is None and os.path.realpath(source) != os.path.realpath(TIMESHIFT_FILE):
            raise RuntimeError("That station is no longer the pause file.")
        if not os.path.isfile(source):
            raise RuntimeError("The pause file is gone.")
        size = os.path.getsize(source)
        start = int(live.get("playhead_byte") or 0)
        if start < 0:
            start = 0
        if size - start < MIN_PLAYABLE_BYTES:
            raise RuntimeError("That pause is too short to keep.")

        rec_dir = recordings_dir or RECORDINGS_DIR
        ensure_private_dir(rec_dir)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = os.path.join(rec_dir, f"{sanitize_filename(tune)}_pause_{stamp}.ts")
        with open(source, "rb") as src, open(dest, "wb") as out:
            src.seek(start)
            left = size - start
            while left > 0:
                chunk = src.read(min(1024 * 1024, left))
                if not chunk:
                    break
                out.write(chunk)
                left -= len(chunk)
        chmod_private_file(dest)
        try:
            service = int(live.get("service_id") or 0)
        except (TypeError, ValueError):
            service = 0
        if service <= 0:
            service = Timeshift.service_id(tune)
        full_mux = bool(live.get("full_mux"))
        ended = os.path.getmtime(source)
        if full_mux:
            rate: Optional[float] = ATSC_BYTES_PER_SEC
        elif live.get("started_at"):
            rate = byte_rate(size, float(live["started_at"]), ended)
        else:
            rate = None
        kept = size - start
        write_sidecar(dest, {
            "title": tune,
            "station": tune,
            "channel": str(live.get("channel") or tune),
            "tune_name": tune,
            "service_id": service,
            "full_mux": full_mux,
            "start": int(ended - kept / rate) if rate else int(time.time()),
            "end": int(ended),
            "byte_rate": rate,
            "status": "complete",
            "kept_from": "pause",
        })
        if os.path.realpath(rec_dir) == os.path.realpath(RECORDINGS_DIR):
            cls.refresh_library_index(recordings_dir=rec_dir)
        return dest

    @classmethod
    def start_recording(cls, channel_query: str, **kwargs: Any) -> DvrSession:
        """Record a channel on Tuner 1. A Guide update gives it up between towers."""
        try:
            with state_lock(TUNER1_LOCK_KEY, timeout=TUNER1_WAIT_SECS):
                return cls._start_recording_locked(channel_query, **kwargs)
        except TimeoutError as exc:
            if str(exc) != TUNER1_LOCK_KEY:
                raise
            raise RuntimeError(
                "Tuner 1 is busy. Stop the recording or wait for the Guide update."
            ) from None

    @classmethod
    def _wait_tuner_free(cls, adapter_id: int, timeout: Optional[float] = None) -> bool:
        """A Guide tower that just let go can take a moment to close the frontend."""
        deadline = time.time() + (FRONTEND_SETTLE_SECS if timeout is None else timeout)
        while True:
            if TunerManager.adapter_is_free(adapter_id):
                return True
            if time.time() >= deadline:
                return False
            time.sleep(0.1)

    @classmethod
    def _start_recording_locked(
        cls,
        channel_query: str,
        duration: Optional[int] = None,
        recordings_dir: Optional[str] = None,
        channels_file: Optional[str] = None,
        mpv_channels_file: Optional[str] = None,
        active_path: Optional[str] = None,
        adapter_override: Optional[int] = None,
        program_title: Optional[str] = None,
    ) -> DvrSession:
        c_path = channels_file or CHANNELS_JSON_PATH
        m_path = mpv_channels_file or MPV_CHANNELS_CONF
        rec_dir = recordings_dir or RECORDINGS_DIR
        act_path = active_path or RECORDINGS_ACTIVE_PATH

        ensure_private_dir(rec_dir)
        cls.enforce_library_budget(recordings_dir=rec_dir, active_path=act_path)

        # 1. Match channel
        channels: List[Dict[str, Any]] = []
        if os.path.exists(c_path):
            try:
                with open(c_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    if isinstance(raw, dict):
                        channels = raw.get("channels", [])
                    elif isinstance(raw, list):
                        channels = raw
            except Exception:
                pass

        matched = match_channel(channel_query, channels) if channels else None
        if matched:
            channel_number = matched.get("channel_number") or channel_query
            station = matched.get("station") or matched.get("name") or channel_query
            tune_name = matched.get("tune_name") or channel_query
        else:
            channel_number = channel_query
            station = channel_query
            tune_name = channel_query

        # Check if already recording this channel
        current_sessions = cls.load_active_sessions(act_path)
        for s in current_sessions:
            if s.is_active() and (s.channel_number == channel_number or s.station == station):
                raise RuntimeError(f"Channel {station} ({channel_number}) is already being recorded (PID {s.pid})")

        # 2. Tuner 1 only. Do not take the live dump card.
        if adapter_override is not None:
            adapter_id = adapter_override
        else:
            adapter_id = WORK_ADAPTER
            held = {
                s.adapter_id
                for s in current_sessions
                if s.is_active() and s.adapter_id == WORK_ADAPTER
            }
            if held or not cls._wait_tuner_free(adapter_id):
                raise RuntimeError(
                    "Tuner 1 is busy. Stop the recording or wait for the Guide update."
                )

        # 3. Lookup Program Metadata — clicked title wins; else the block on now
        chosen = str(program_title or "").strip()
        if chosen:
            program_title = chosen
        else:
            program_title = "Live Broadcast"
            try:
                guide_data = load_guide()
                prog = get_channel_program(channel_number, guide_data=guide_data)
                program_title = current_program_title(prog)
            except Exception:
                pass

        # 4. Generate Target File and Socket Path
        now = datetime.now()
        timestamp_str = now.strftime("%Y%m%d_%H%M%S")
        safe_station = sanitize_filename(station)
        safe_channel = sanitize_filename(channel_number)
        safe_title = sanitize_filename(program_title)
        filename = f"{safe_channel}-{safe_station}_{safe_title}_{timestamp_str}.ts"
        file_path = os.path.join(rec_dir, filename)
        touch_private_file(file_path)

        session_id = f"dvr-{safe_channel}-{int(time.time())}"
        socket_path = get_runtime_socket(f"omarchy-tv-{session_id}.sock")

        if os.path.exists(socket_path):
            try:
                os.unlink(socket_path)
            except OSError:
                pass

        from engine.timeshift import Timeshift

        full_mux = bool(Timeshift._conf_needs_full_mux(tune_name))
        try:
            service_id = int(Timeshift.service_id(tune_name) or 0)
        except (TypeError, ValueError):
            service_id = 0
        started = time.time()
        side = {
            "title": program_title,
            "station": station,
            "channel": channel_number,
            "tune_name": tune_name,
            "service_id": service_id,
            "full_mux": full_mux,
            "start": int(started),
            "end": None,
            "planned_end": int(started + duration) if duration and duration > 0 else None,
            "status": "recording",
        }

        # 5. Build MPV Dumper Command. A copied video id dumps the whole tower.
        cmd = [
            "mpv",
            f"--stream-dump={file_path}",
            "--vo=null",
            "--ao=null",
            "--cache=yes",
            f"--input-ipc-server={socket_path}",
            f"--dvbin-card={adapter_id}",
            f"--dvbin-file={m_path}",
            "--idle=no",
        ]
        if full_mux:
            cmd.append("--dvbin-full-transponder=yes")
        cmd.append(f"dvb://{tune_name}")

        proc = subprocess.Popen(
            own_scope(cmd),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        chmod_private_file(file_path)
        if not cls.wait_until_growing(proc, file_path):
            if proc.poll() is None:
                try:
                    proc.kill()
                except OSError:
                    pass
            side["status"] = "failed"
            write_sidecar(file_path, side)
            raise RuntimeError(
                "Recorder did not start writing. The partial file was kept."
            )

        write_sidecar(file_path, side)
        session = DvrSession(
            session_id=session_id,
            channel_number=channel_number,
            station=station,
            tune_name=tune_name,
            program_title=program_title,
            start_time=started,
            duration_seconds=duration,
            adapter_id=adapter_id,
            file_path=file_path,
            socket_path=socket_path,
            pid=proc.pid,
        )

        with state_lock(act_path):
            fresh = cls.load_active_sessions(act_path)
            fresh.append(session)
            cls.save_active_sessions(fresh, act_path)
        if os.path.realpath(rec_dir) == os.path.realpath(RECORDINGS_DIR):
            cls.refresh_library_index(recordings_dir=rec_dir)

        return session

    @classmethod
    def stop_recording(
        cls,
        channel_query: Optional[str] = None,
        active_path: Optional[str] = None,
    ) -> List[DvrSession]:
        """Stops active recording session(s). Returns list of stopped sessions."""
        act_path = active_path or RECORDINGS_ACTIVE_PATH
        with state_lock(act_path):
            stopped = cls._stop_matching(channel_query, act_path)
        cls.refresh_library_index()
        return stopped

    @classmethod
    def _stop_matching(cls, channel_query: Optional[str], act_path: str) -> List[DvrSession]:
        current_sessions = cls.load_active_sessions(act_path)
        stopped: List[DvrSession] = []
        remaining: List[DvrSession] = []

        for s in current_sessions:
            match = False
            if channel_query is None:
                match = True
            elif (
                s.channel_number == channel_query
                or s.station.lower() == channel_query.lower()
                or s.session_id == channel_query
                or str(s.pid) == channel_query
            ):
                match = True

            if match:
                s.stop()
                if s.file_path:
                    end = int(time.time())
                    patch_sidecar(s.file_path, status="complete", end=end,
                                  byte_rate=byte_rate(s.get_file_size(), s.start_time, end))
                stopped.append(s)
            else:
                remaining.append(s)

        cls.save_active_sessions(remaining, act_path)
        return stopped

    @classmethod
    def list_recordings(cls, recordings_dir: Optional[str] = None) -> List[Dict[str, Any]]:
        """Scans recordings directory for completed or in-progress TS/MKV video files."""
        rec_dir = recordings_dir or RECORDINGS_DIR
        if not os.path.exists(rec_dir):
            return []

        results = []
        for entry in os.scandir(rec_dir):
            if entry.is_file(follow_symlinks=False) and entry.name.lower().endswith((".ts", ".mkv", ".mp4")):
                try:
                    stat = entry.stat()
                    # Parse filename parts: e.g. 8.1-FOX_FOX_8_News_20260920_163200.ts
                    m = re.match(r"^([0-9\.\-]+)-([^_]+)_(.+)_([0-9]{8}_[0-9]{6})\.", entry.name)
                    if m:
                        ch_num, station, title_raw, ts_raw = m.groups()
                        title = title_raw.replace("_", " ")
                    else:
                        ch_num = ""
                        station = ""
                        title = entry.name
                        ts_raw = ""

                    side = read_sidecar(entry.path)
                    if side:
                        title = str(side.get("title") or title)
                        station = str(side.get("station") or station)
                        ch_num = str(side.get("channel") or ch_num)
                    status = str(side.get("status") or "")
                    try:
                        service_id = int(side.get("service_id") or 0)
                    except (TypeError, ValueError):
                        service_id = 0
                    playable = stat.st_size >= MIN_PLAYABLE_BYTES

                    results.append({
                        "name": entry.name,
                        "path": entry.path,
                        "size_bytes": stat.st_size,
                        "size_formatted": format_bytes(stat.st_size),
                        "playable": playable,
                        "mtime": stat.st_mtime,
                        "date_formatted": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                        "channel_number": ch_num,
                        "station": station,
                        "title": title,
                        "status": status,
                        "service_id": service_id,
                        "full_mux": bool(side.get("full_mux")) if side else False,
                        "start": side.get("start"),
                        "end": side.get("end"),
                    })
                except OSError:
                    continue

        results.sort(key=lambda x: x["mtime"], reverse=True)
        return results

    @classmethod
    def enforce_library_budget(
        cls,
        recordings_dir: Optional[str] = None,
        prefs: Optional[Dict[str, Any]] = None,
        keep_paths: Optional[Set[str]] = None,
        active_path: Optional[str] = None,
    ) -> List[str]:
        """Deletes oldest finished recordings until the library is within cap."""
        rec_dir = recordings_dir or RECORDINGS_DIR
        budget = resolve_library_budget_bytes(rec_dir, prefs=prefs)
        if budget is None:
            return []

        protected: Set[str] = set()
        for path in keep_paths or []:
            try:
                protected.add(os.path.realpath(path))
            except OSError:
                continue
        for session in cls.load_active_sessions(active_path or RECORDINGS_ACTIVE_PATH):
            if session.is_active() and session.file_path:
                try:
                    protected.add(os.path.realpath(session.file_path))
                except OSError:
                    continue

        recordings = cls.list_recordings(recordings_dir=rec_dir)
        used = sum(item["size_bytes"] for item in recordings)
        if used <= budget:
            return []

        rec_real = os.path.realpath(rec_dir)
        removed: List[str] = []
        quiet_before = time.time() - PRUNE_QUIET_SECS
        for item in sorted(recordings, key=lambda rec: rec.get("mtime") or 0):
            if used <= budget:
                break
            if float(item.get("mtime") or 0) > quiet_before:
                continue
            path = item.get("path") or ""
            try:
                if os.path.islink(path):
                    continue
                real_path = os.path.realpath(path)
                if os.path.commonpath([rec_real, real_path]) != rec_real:
                    continue
            except (OSError, ValueError):
                continue
            if real_path in protected:
                continue
            try:
                os.remove(path)
            except OSError:
                continue
            try:
                os.remove(sidecar_path(path))
            except OSError:
                pass
            used -= int(item.get("size_bytes") or 0)
            removed.append(path)
        return removed

    @classmethod
    def refresh_library_index(
        cls,
        recordings_dir: Optional[str] = None,
        index_path: Optional[str] = None,
        prefs: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Writes recordings.json atomically for the Quickshell library view."""
        rec_dir = recordings_dir or RECORDINGS_DIR
        cls.enforce_library_budget(recordings_dir=rec_dir, prefs=prefs)
        recordings = cls.list_recordings(recordings_dir=rec_dir)
        used = sum(item["size_bytes"] for item in recordings)
        budget = resolve_library_budget_bytes(rec_dir, prefs=prefs)
        raw_cap = (prefs if prefs is not None else load_ui_prefs()).get("library_max_gb", "auto")
        target_path = index_path or RECORDINGS_INDEX_PATH
        os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
        tmp_path = f"{target_path}.tmp.{os.getpid()}"
        payload = {
            "recordings": recordings,
            "updated_at": time.time(),
            "library_bytes": used,
            "library_bytes_formatted": format_bytes(used),
            "library_budget_bytes": budget,
            "library_budget_formatted": format_bytes(budget) if budget else "Unlimited",
            "library_max_gb": raw_cap,
        }
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp_path, target_path)
        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        return recordings

    @classmethod
    def delete_recording(cls, file_path: str, recordings_dir: Optional[str] = None) -> bool:
        """Securely deletes a recording within the allowed recordings directory."""
        rec_dir = os.path.realpath(recordings_dir or RECORDINGS_DIR)
        real_file = os.path.realpath(file_path)

        # Path traversal guard
        common = os.path.commonpath([rec_dir, real_file])
        if common != rec_dir:
            raise PermissionError(f"Access denied: {file_path} is outside allowed recordings directory")

        if os.path.exists(real_file):
            os.remove(real_file)
            side = sidecar_path(real_file)
            if os.path.isfile(side) and not os.path.islink(side):
                try:
                    if os.path.commonpath([rec_dir, os.path.realpath(side)]) == rec_dir:
                        os.remove(side)
                except (OSError, ValueError):
                    pass
            if recordings_dir is None or os.path.realpath(recordings_dir) == os.path.realpath(RECORDINGS_DIR):
                cls.refresh_library_index(recordings_dir=recordings_dir)
            return True
        return False
