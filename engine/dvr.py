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
import sys
import subprocess
import shutil
from datetime import datetime
from typing import List, Dict, Optional, Any, Set

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

from engine.paths import (
    CHANNELS_JSON_PATH,
    MPV_CHANNELS_CONF,
    RECORDINGS_DIR,
    RECORDINGS_ACTIVE_PATH,
    RECORDINGS_INDEX_PATH,
    UI_PREFS_PATH,
    get_runtime_socket,
)
from engine.tuner import TunerManager
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
        os.makedirs(recordings_dir, exist_ok=True)
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

    @classmethod
    def save_active_sessions(cls, sessions: List[DvrSession], active_path: Optional[str] = None) -> None:
        """Atomically saves active recording sessions to JSON."""
        target_path = active_path or RECORDINGS_ACTIVE_PATH
        os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
        tmp_path = f"{target_path}.tmp.{os.getpid()}"

        data = [s.to_dict() for s in sessions if s.is_active()]
        try:
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
    def start_recording(
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
        """
        Allocates an ATSC tuner and initiates background recording of a channel.
        """
        c_path = channels_file or CHANNELS_JSON_PATH
        m_path = mpv_channels_file or MPV_CHANNELS_CONF
        rec_dir = recordings_dir or RECORDINGS_DIR
        act_path = active_path or RECORDINGS_ACTIVE_PATH

        # Ensure recordings directory exists
        os.makedirs(rec_dir, mode=0o755, exist_ok=True)
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

        # 2. Allocate Tuner
        if adapter_override is not None:
            adapter_id = adapter_override
        else:
            busy_adapters = {s.adapter_id for s in current_sessions if s.is_active()}
            available_tuner = TunerManager.get_available_tuner(require_atsc=True, exclude_adapters=busy_adapters)
            if not available_tuner:
                raise RuntimeError("No available ATSC tuners. All tuners are currently in use for playback or recording.")
            adapter_id = available_tuner.adapter_id

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

        session_id = f"dvr-{safe_channel}-{int(time.time())}"
        socket_path = get_runtime_socket(f"omarchy-tv-{session_id}.sock")

        if os.path.exists(socket_path):
            try:
                os.unlink(socket_path)
            except OSError:
                pass

        # 5. Build MPV Dumper Command
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
            f"dvb://{tune_name}",
        ]

        # Launch background process detached
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        exited = proc.poll()
        if isinstance(exited, int):
            raise RuntimeError("Recorder exited before the tuner locked. Try again when a tuner is free.")

        session = DvrSession(
            session_id=session_id,
            channel_number=channel_number,
            station=station,
            tune_name=tune_name,
            program_title=program_title,
            start_time=time.time(),
            duration_seconds=duration,
            adapter_id=adapter_id,
            file_path=file_path,
            socket_path=socket_path,
            pid=proc.pid,
        )

        current_sessions.append(session)
        cls.save_active_sessions(current_sessions, act_path)
        if os.path.realpath(rec_dir) == os.path.realpath(RECORDINGS_DIR):
            cls.refresh_library_index(recordings_dir=rec_dir)

        # 6. If duration is set, schedule background termination via detached timer process
        if duration and duration > 0:
            timer_code = (
                f"import sys, time; sys.path.insert(0, {repr(PROJECT_ROOT)});"
                f"from engine.dvr import DvrManager;"
                f"time.sleep({float(duration)});"
                f"DvrManager.stop_recording({repr(session.session_id)}, active_path={repr(act_path)})"
            )
            subprocess.Popen(
                [sys.executable, "-c", timer_code],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

        return session

    @classmethod
    def stop_recording(
        cls,
        channel_query: Optional[str] = None,
        active_path: Optional[str] = None,
    ) -> List[DvrSession]:
        """Stops active recording session(s). Returns list of stopped sessions."""
        act_path = active_path or RECORDINGS_ACTIVE_PATH
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
                stopped.append(s)
            else:
                remaining.append(s)

        cls.save_active_sessions(remaining, act_path)
        cls.refresh_library_index()
        return stopped

    @classmethod
    def list_recordings(cls, recordings_dir: Optional[str] = None) -> List[Dict[str, Any]]:
        """Scans recordings directory for completed or in-progress TS/MKV video files."""
        rec_dir = recordings_dir or RECORDINGS_DIR
        if not os.path.exists(rec_dir):
            return []

        results = []
        for entry in os.scandir(rec_dir):
            if entry.is_file() and entry.name.lower().endswith((".ts", ".mkv", ".mp4")):
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

                    results.append({
                        "name": entry.name,
                        "path": entry.path,
                        "size_bytes": stat.st_size,
                        "size_formatted": format_bytes(stat.st_size),
                        "playable": stat.st_size >= MIN_PLAYABLE_BYTES,
                        "mtime": stat.st_mtime,
                        "date_formatted": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
                        "channel_number": ch_num,
                        "station": station,
                        "title": title,
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

        removed: List[str] = []
        for item in sorted(recordings, key=lambda rec: rec.get("mtime") or 0):
            if used <= budget:
                break
            path = item.get("path") or ""
            try:
                real_path = os.path.realpath(path)
            except OSError:
                continue
            if real_path in protected:
                continue
            try:
                os.remove(real_path)
            except OSError:
                continue
            used -= int(item.get("size_bytes") or 0)
            removed.append(real_path)
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
            if recordings_dir is None or os.path.realpath(recordings_dir) == os.path.realpath(RECORDINGS_DIR):
                cls.refresh_library_index(recordings_dir=recordings_dir)
            return True
        return False
