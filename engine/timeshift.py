"""
Throwaway pause-live buffer: dump Tuner 0 to a growing MPEG-TS file.

A detached reader copies live.ts onto a fifo and outlives `omarchy-tv play`.
The window opens that fifo once. Skip and live SEEK the reader. Channel
change is the only loadfile. Close TV wipes the dump and the reader. This
is not a library recording and not dvb:// cache.
"""

import json
import os
import re
import shutil
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from typing import Any, Dict, Optional

from engine.paths import (
    CHANNELS_JSON_PATH,
    FOLLOW_FIFO_PATH,
    FOLLOW_SOCKET_PATH,
    MPV_CHANNELS_CONF,
    TIMESHIFT_ACTIVE_PATH,
    TIMESHIFT_DIR,
    TIMESHIFT_FILE,
    TIMESHIFT_SOCKET_PATH,
    TUNE_LOCK_PATH,
    TUNE_STATUS_PATH,
    chmod_private_file,
    ensure_private_dir,
    state_lock,
    touch_private_file,
)

FOLLOW_TS_PY = os.path.join(os.path.dirname(os.path.realpath(__file__)), "follow_ts.py")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

# Same floor as library dumps: PAT/PMT-only is not a picture.
MIN_PLAYABLE_BYTES = 256 * 1024
# ATSC lock plus PAT/PMT can exceed a few seconds. Do not kill a dump that is
# still writing just because this floor is not hit yet.
DUMP_WAIT_SECS = 20
DUMP_GROWING_BYTES = 32 * 1024
# lavf reads this much before the first frame. A subchannel runs near 140 KB/s,
# so the 5 MB default is half a minute of air. Under ~4 s of air it misses streams.
PROBE_AIR_SEC = 6.0
PROBE_MIN_BYTES = 750_000
PROBE_MAX_BYTES = 5_000_000


TS_PACKET = 188
ATSC_BPS = 19_390_000
PAUSE_CAP_SEC = 3600
SEEK_STEP = 10.0
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
    # Bytes/sec of the station the last wait saw arrive. 0 when too quick to tell.
    _open_bps = 0.0

    @classmethod
    def _note_open_rate(cls, t0: float, s0: int, size: int) -> None:
        elapsed = time.time() - t0
        cls._open_bps = (size - s0) / elapsed if elapsed >= 0.3 and size > s0 else 0.0

    @classmethod
    def acquire_tune_lock(cls) -> bool:
        """Marks an in-flight retune so sync/Cmd+W cannot wipe the new dump.

        Returns False if another living process already holds the lock.
        """
        with state_lock(TUNE_LOCK_PATH):
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
        return ensure_private_dir(TIMESHIFT_DIR)

    @classmethod
    def dump_path(cls) -> str:
        return TIMESHIFT_FILE

    @classmethod
    def patch_state(cls, **fields: Any) -> None:
        with state_lock(TIMESHIFT_ACTIVE_PATH):
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
    def live_join_byte(cls) -> int:
        """Far enough back from the write head for a keyframe. The last packet is torn."""
        size = cls.dump_bytes()
        back = 512 * 1024
        if size <= back + TS_PACKET:
            return 0
        return align_ts(size - back)

    @classmethod
    def play_from_byte(cls) -> int:
        """Where the picture should open after a zap. 0 is the start of live.ts."""
        try:
            return align_ts(int(cls.load_state().get("play_from") or 0))
        except (TypeError, ValueError):
            return 0

    @classmethod
    def picture_open_byte(cls) -> int:
        """Start where about a second of this open is already in the file.

        A fresh dump is still short, so that place is the start. A long file
        opens a couple of megabytes back from the live edge.
        """
        mark = cls.play_from_byte()
        size = cls.dump_bytes()
        back = 2 * 1024 * 1024
        if size <= mark + back:
            return mark
        return align_ts(size - back)

    @classmethod
    def picture_probe_bytes(cls) -> int:
        """About six seconds of this station. A whole-tower dump keeps the default."""
        state = cls.load_state()
        if state.get("full_mux"):
            return PROBE_MAX_BYTES
        try:
            bps = float(state.get("open_bps") or 0)
        except (TypeError, ValueError):
            bps = 0.0
        if bps <= 0:
            return PROBE_MAX_BYTES
        return int(min(PROBE_MAX_BYTES, max(PROBE_MIN_BYTES, bps * PROBE_AIR_SEC)))

    @classmethod
    def write_rate(cls) -> float:
        """Bytes/sec the dump file is growing. Pause and play share this rate."""
        state = cls.load_state()
        size = cls.dump_bytes()
        now = time.time()
        try:
            raw_mark = state.get("rate_byte")
            mark_b = int(raw_mark) if raw_mark is not None else -1
        except (TypeError, ValueError):
            mark_b = -1
        try:
            mark_t = float(state.get("rate_t") or 0)
        except (TypeError, ValueError):
            mark_t = 0.0
        if mark_t <= 0 or mark_b < 0 or size < mark_b:
            cls.patch_state(rate_byte=size, rate_t=now)
        else:
            elapsed = now - mark_t
            grown = size - mark_b
            # A short window is a spike. Once a rate is known, a new window only nudges it,
            # or the behind clock jumps while the picture stays put.
            if elapsed >= 5 and grown > 0:
                measured = grown / elapsed
                if measured >= 1000:
                    try:
                        prev = float(state.get("mux_bps") or 0)
                    except (TypeError, ValueError):
                        prev = 0.0
                    if prev >= 1000:
                        if measured < prev * 0.5:
                            measured = prev
                        elif measured > prev * 3:
                            pass
                        else:
                            measured = prev * 0.85 + measured * 0.15
                    cls.patch_state(rate_byte=size, rate_t=now, mux_bps=measured)
                    return measured
        try:
            bps = float(cls.load_state().get("mux_bps") or 0)
        except (TypeError, ValueError):
            bps = 0.0
        if bps >= 1000:
            return bps
        return ATSC_BPS / 8.0

    @classmethod
    def pause_cap_bytes(cls) -> int:
        """One hour of ATSC air. The pause file may grow this far past the playhead."""
        return int(ATSC_BPS / 8.0 * PAUSE_CAP_SEC)

    @classmethod
    def hold_dump_if_full(cls) -> bool:
        """Stop the tuner dump an hour ahead of the playhead, or when the disk is low.

        The file, the picture, and the playhead stay. A later Live still jumps
        to the write head that remains. dump_held says which: "hour" or "disk".
        """
        state = cls.load_state()
        if not state or state.get("dump_held"):
            return False
        pid = int(state.get("pid") or 0)
        if not cls._pid_alive(pid):
            return False
        from engine.dvr import disk_below_floor
        reason = "disk" if disk_below_floor(TIMESHIFT_DIR) else ""
        # Live playback reads the write head. playhead_byte stays put, so the
        # file size alone is not "an hour ahead."
        watching_live = str(state.get("view") or "live") == "live" and not bool(state.get("paused"))
        if not reason and not watching_live and cls.dump_bytes() - cls.playhead_now() >= cls.pause_cap_bytes():
            reason = "hour"
        if not reason:
            return False
        sock = str(state.get("socket") or TIMESHIFT_SOCKET_PATH)
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
        if os.path.exists(sock):
            try:
                os.unlink(sock)
            except OSError:
                pass
        cls.patch_state(pid=0, dump_held=reason)
        return True

    @classmethod
    def delay_sec(cls) -> float:
        """File end minus the cursor, at the measured dump rate.

        Live and unpaused is the write head, so the gap is zero. Pause and
        play use this same subtraction. Neither one starts a clock.
        """
        state = cls.load_state()
        if str(state.get("view") or "live") == "live" and not bool(state.get("paused")):
            return 0.0
        rate = cls.write_rate()
        if rate <= 0:
            return 0.0
        return max(0.0, (cls.dump_bytes() - cls.playhead_now() - cls.live_lag_bytes()) / rate)

    @classmethod
    def live_lag_bytes(cls) -> int:
        """The gap a live picture already had: the tune and mpv's start. It is not behind."""
        try:
            return max(0, int(cls.load_state().get("live_lag") or 0))
        except (TypeError, ValueError):
            return 0

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
        """Reader cursor. Live playback sits on the write head. A pause leaves it."""
        state = cls.load_state()
        view = str(state.get("view") or "live")
        paused = bool(state.get("paused"))
        if view == "live" and not paused:
            return cls.live_edge_byte()
        pos = cls.follow_pos() if state.get("follow_socket") else None
        if pos is None:
            try:
                pos = int(state.get("playhead_byte") or 0)
            except (TypeError, ValueError):
                pos = 0
        size = cls.dump_bytes()
        if size > TS_PACKET:
            pos = min(pos, size - TS_PACKET)
        return align_ts(max(0, int(pos)))

    @classmethod
    def remain_sec(cls) -> float:
        rate = cls.mux_rate()
        if rate <= 0:
            return 0.0
        return max(0.0, (cls.dump_bytes() - cls.playhead_now()) / rate)

    @classmethod
    def fwd_hop(cls, remain: float) -> float:
        """Ten seconds closer to live. Inside that last ten, the next press is live."""
        if remain <= SEEK_STEP:
            return 0.0
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
        with state_lock(TIMESHIFT_ACTIVE_PATH):
            tmp = f"{TIMESHIFT_ACTIVE_PATH}.tmp.{os.getpid()}"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp, TIMESHIFT_ACTIVE_PATH)

    @classmethod
    def load_tune_status(cls) -> Dict[str, Any]:
        try:
            with open(TUNE_STATUS_PATH, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    @classmethod
    def _write_tune_status(cls, payload: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(TUNE_STATUS_PATH), exist_ok=True)
        tmp = f"{TUNE_STATUS_PATH}.tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, TUNE_STATUS_PATH)

    @classmethod
    def patch_tune_status(cls, **fields: Any) -> None:
        data = cls.load_tune_status()
        data.update(fields)
        cls._write_tune_status(data)

    @classmethod
    def begin_tune(cls, tune_name: str, display_name: str = "") -> None:
        cls._write_tune_status({
            "phase": "tuning",
            "tune_name": tune_name,
            "display_name": display_name or tune_name,
            "snr_db": None,
            "message": "",
        })

    @classmethod
    def fail_tune(cls, tune_name: str, display_name: str = "", message: str = "") -> None:
        prior = cls.load_tune_status()
        label = (display_name or tune_name or "That station").strip()
        cls._write_tune_status({
            "phase": "failed",
            "tune_name": tune_name,
            "display_name": label,
            "snr_db": prior.get("snr_db"),
            "message": message or f"{label} did not come up",
        })

    @classmethod
    def finish_tune(cls) -> None:
        cls._write_tune_status({
            "phase": "ok",
            "tune_name": "",
            "display_name": "",
            "snr_db": None,
            "message": "",
        })

    @classmethod
    def _snr_db_from_log(cls, log_path: str) -> Optional[float]:
        """Last SNR in an mpv dump log. This tuner reports tenths of a dB."""
        try:
            with open(log_path, "rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - 80000))
                text = f.read().decode("utf-8", "replace")
        except OSError:
            return None
        found = None
        for match in re.finditer(r"SNR:\s*(\d+)", text):
            found = int(match.group(1))
        if found is None:
            return None
        return round(found / 10.0, 1)

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
        for path in (FOLLOW_FIFO_PATH, cls._follow_pos_path(sock)):
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
        if state:
            with state_lock(TIMESHIFT_ACTIVE_PATH):
                fresh = cls.load_state()
                if fresh:
                    fresh.pop("follow_pid", None)
                    fresh.pop("follow_socket", None)
                    fresh["updated_at"] = time.time()
                    cls._write_state(fresh)

    @classmethod
    def _follow_pos_path(cls, sock: str) -> str:
        if sock.endswith(".sock"):
            return sock[:-5] + ".pos"
        return sock + ".pos"

    @classmethod
    def _fifo_is_fifo(cls) -> bool:
        try:
            return stat.S_ISFIFO(os.stat(FOLLOW_FIFO_PATH).st_mode)
        except OSError:
            return False

    @classmethod
    def start_follow(cls, start_byte: int = 0) -> Optional[int]:
        """Detached reader. Its fifo outlives this command. A live reader stays."""
        state = cls.load_state()
        pid = int(state.get("follow_pid") or 0)
        if cls._pid_alive(pid) and cls._fifo_is_fifo():
            return pid
        cls.stop_follow()
        sock = FOLLOW_SOCKET_PATH
        fifo = FOLLOW_FIFO_PATH
        for path in (sock, fifo):
            if os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
        try:
            os.mkfifo(fifo, 0o600)
        except OSError:
            return None
        try:
            os.chmod(fifo, 0o600)
        except OSError:
            pass
        proc = subprocess.Popen(
            [
                sys.executable,
                FOLLOW_TS_PY,
                TIMESHIFT_FILE,
                str(max(0, int(start_byte))),
                sock,
                fifo,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        if isinstance(proc.poll(), int):
            return None
        cls.patch_state(follow_pid=proc.pid, follow_socket=sock)
        cls._detach_child(proc)
        return proc.pid

    @classmethod
    def _detach_child(cls, proc: subprocess.Popen) -> None:
        """The follower outlives this call. Popen.__del__ warns if returncode is unset."""
        if proc.returncode is not None:
            return
        proc.returncode = 0

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
                except FileNotFoundError:
                    return
                except Exception:
                    busy = True
                    break
            if not busy:
                return
            time.sleep(0.03)

    @classmethod
    def _conf_rows(cls) -> list:
        rows = []
        try:
            with open(MPV_CHANNELS_CONF, encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split(":")
                    if len(parts) < 6 or not parts[0]:
                        continue
                    try:
                        rows.append({
                            "name": parts[0],
                            "freq": int(parts[1]),
                            "video": int(parts[3] or 0),
                            "audio": int(parts[4] or 0),
                            "sid": int(parts[5] or 0),
                        })
                    except ValueError:
                        continue
        except OSError:
            pass
        return rows

    @classmethod
    def _conf_needs_full_mux(cls, tune_name: str) -> bool:
        """A missing video id, or one another service on this tower already uses.

        The scanner copies an earlier service's video id onto a later one.
        The lowest service id keeps that id. The copy is played from the
        whole tower by its own service id. The callsign and the channel
        number are one service.
        """
        video, audio = cls._conf_pids(tune_name)
        if video <= 0 or audio <= 0:
            return True
        return cls._video_pid_is_copied(tune_name)

    @classmethod
    def _video_pid_is_copied(cls, tune_name: str) -> bool:
        name = (tune_name or "").strip()
        rows = cls._conf_rows()
        mine = next((row for row in rows if row["name"] == name), None)
        if not mine or mine["video"] <= 0 or mine["sid"] <= 0:
            return False
        owners = [
            row["sid"] for row in rows
            if row["freq"] == mine["freq"] and row["video"] == mine["video"] and row["sid"] > 0
        ]
        if not owners:
            return False
        return mine["sid"] != min(owners)

    @classmethod
    def _conf_freq(cls, tune_name: str) -> int:
        name = (tune_name or "").strip()
        for row in cls._conf_rows():
            if row["name"] == name:
                return row["freq"]
        return 0

    @classmethod
    def _conf_pids(cls, tune_name: str) -> tuple:
        name = (tune_name or "").strip()
        for row in cls._conf_rows():
            if row["name"] == name:
                return row["video"], row["audio"]
        return 0, 0

    @classmethod
    def service_id(cls, tune_name: str) -> int:
        name = (tune_name or "").strip()
        for row in cls._conf_rows():
            if row["name"] == name:
                return row["sid"]
        return 0

    @classmethod
    def _conf_name_shared(cls, tune_name: str) -> bool:
        name = (tune_name or "").strip()
        if not name:
            return False
        return sum(1 for row in cls._conf_rows() if row["name"] == name) > 1

    @classmethod
    def conf_name(cls, channel: Dict[str, Any]) -> str:
        """The channels.conf line for this service.

        A repeated tune name is only the first row. The channel number line
        is the one that selects 28.2 instead of 28.1.
        """
        tune = str(channel.get("tune_name") or channel.get("name") or "").strip()
        number = str(channel.get("channel_number") or "").strip()
        if number and cls._conf_name_shared(tune):
            return number
        return tune or number

    @classmethod
    def _remember_pids(cls, dump_path: str, frequency: Optional[int] = None) -> bool:
        """Learn video and audio IDs from a full-mux dump and save them."""
        try:
            with open(dump_path, "rb") as f:
                if f.read(1) != b"\x47":
                    return False
        except OSError:
            return False
        sample = os.path.join(os.path.dirname(dump_path), "pids.ts")
        try:
            with open(dump_path, "rb") as src, open(sample, "wb") as dst:
                dst.write(src.read(1024 * 1024))
            probe = subprocess.run(
                ["ffprobe", "-v", "fatal", "-show_programs", "-of", "json", sample],
                capture_output=True,
                text=True,
                timeout=15,
            )
            data = json.loads(probe.stdout or "{}")
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
            return False
        finally:
            try:
                os.remove(sample)
            except OSError:
                pass
        learned = {}
        for program in data.get("programs") or []:
            try:
                sid = int(program.get("program_id"))
            except (TypeError, ValueError):
                continue
            video = audio = 0
            for stream in program.get("streams") or []:
                try:
                    pid = int(str(stream.get("id")), 16)
                except (TypeError, ValueError):
                    continue
                kind = stream.get("codec_type")
                if kind == "video" and video <= 0:
                    video = pid
                elif kind == "audio" and audio <= 0:
                    audio = pid
            if sid > 0 and video > 0 and audio > 0:
                learned[sid] = (video, audio)
        if not learned:
            return False
        cls._write_learned_pids(learned, frequency, trust=True)
        return True

    @classmethod
    def _write_learned_pids(
        cls,
        learned: Dict[int, tuple],
        frequency: Optional[int] = None,
        trust: bool = False,
    ) -> None:
        """Save video and audio IDs by service id.

        trust: the IDs came from the tower's PMT or a probe of it, so any
        service on that tower that differs is corrected, not only a copy.
        """
        with state_lock(MPV_CHANNELS_CONF):
            cls._write_learned_pids_locked(learned, frequency, trust)

    @classmethod
    def _write_learned_pids_locked(
        cls,
        learned: Dict[int, tuple],
        frequency: Optional[int],
        trust: bool,
    ) -> None:
        try:
            with open(MPV_CHANNELS_CONF, encoding="utf-8") as f:
                lines = f.read().splitlines()
        except OSError:
            lines = []
        lowest = {}
        for line in lines:
            parts = line.split(":")
            if len(parts) < 6:
                continue
            try:
                freq = int(parts[1])
                video = int(parts[3] or 0)
                sid = int(parts[5] or 0)
            except ValueError:
                continue
            if video <= 0 or sid <= 0:
                continue
            key = (freq, video)
            if key not in lowest or sid < lowest[key]:
                lowest[key] = sid
        changed = False
        out = []
        for line in lines:
            parts = line.split(":")
            if len(parts) >= 6:
                try:
                    freq = int(parts[1])
                    old_video = int(parts[3] or 0)
                    old_audio = int(parts[4] or 0)
                    sid = int(parts[5])
                except ValueError:
                    freq = old_video = old_audio = 0
                    sid = -1
                on_tower = frequency is None or freq == frequency
                copied = old_video > 0 and sid > 0 and sid != lowest.get((freq, old_video))
                if on_tower and sid in learned and (trust or old_video <= 0 or old_audio <= 0 or copied):
                    video, audio = learned[sid]
                    if old_video != video or old_audio != audio:
                        parts[3] = str(video)
                        parts[4] = str(audio)
                        line = ":".join(parts)
                        changed = True
            out.append(line)
        if changed:
            tmp = f"{MPV_CHANNELS_CONF}.tmp.{os.getpid()}"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write("\n".join(out) + ("\n" if out else ""))
            chmod_private_file(tmp)
            os.replace(tmp, MPV_CHANNELS_CONF)
        try:
            with open(CHANNELS_JSON_PATH, encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        channels = payload.get("channels") if isinstance(payload, dict) else None
        if not isinstance(channels, list):
            return
        touched = False
        for ch in channels:
            if not isinstance(ch, dict):
                continue
            try:
                sid = int(ch.get("service_id"))
            except (TypeError, ValueError):
                continue
            if sid not in learned:
                continue
            try:
                ch_freq = int(ch.get("frequency"))
            except (TypeError, ValueError):
                ch_freq = None
            if frequency is not None and ch_freq != frequency:
                continue
            video, audio = learned[sid]
            old_video = int(ch.get("video_pid") or 0)
            old_audio = int(ch.get("audio_pid") or 0)
            copied = (
                ch_freq is not None
                and old_video > 0
                and sid != lowest.get((ch_freq, old_video))
            )
            if (trust or old_video <= 0 or old_audio <= 0 or copied) and (old_video, old_audio) != (video, audio):
                ch["video_pid"] = video
                ch["audio_pid"] = audio
                touched = True
        if not touched:
            return
        tmp = f"{CHANNELS_JSON_PATH}.tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        chmod_private_file(tmp)
        os.replace(tmp, CHANNELS_JSON_PATH)

    @classmethod
    def _capture_dump(
        cls,
        name: str,
        adapter_id: int,
        dest: str,
        sock: str,
        log_name: str,
    ) -> Optional[subprocess.Popen]:
        needs_full = cls._conf_needs_full_mux(name)
        proc = cls._spawn_dump(name, adapter_id, dest, sock, log_name=log_name)
        if proc is None:
            return None
        log_path = os.path.join(TIMESHIFT_DIR, log_name)
        if not cls._wait_dump_playable(proc, dest, log_path):
            cls._kill_pid(proc.pid)
            return None
        if needs_full:
            cls._learn_pids_later(dest, cls._conf_freq(name) or None)
        return proc

    @classmethod
    def _learn_pids_later(cls, dump_path: str, frequency: Optional[int] = None) -> None:
        """A whole-tower dump is playable now. Learn the real ids off the zap."""
        def run() -> None:
            cls._remember_pids(dump_path, frequency)

        threading.Thread(target=run, daemon=True).start()

    @classmethod
    def _retire_dump_file(cls) -> None:
        """Move live.ts aside and delete it off the zap. Rename is the fast part."""
        if not os.path.isfile(TIMESHIFT_FILE):
            return
        retired = f"{TIMESHIFT_FILE}.old.{os.getpid()}.{int(time.time())}"
        try:
            os.replace(TIMESHIFT_FILE, retired)
        except OSError:
            return

        def drop(path: str) -> None:
            try:
                os.remove(path)
            except OSError:
                pass

        threading.Thread(target=drop, args=(retired,), daemon=True).start()

    @classmethod
    def _dump_command(cls, command: list, timeout: float = 35.0) -> Optional[dict]:
        state = cls.load_state()
        sock = str(state.get("socket") or TIMESHIFT_SOCKET_PATH)
        if not os.path.exists(sock):
            return None
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(timeout)
                s.connect(sock)
                s.sendall((json.dumps({"command": command}) + "\n").encode("utf-8"))
                buf = ""
                deadline = time.time() + timeout
                while time.time() < deadline:
                    try:
                        chunk = s.recv(4096)
                    except socket.timeout:
                        return None
                    if not chunk:
                        break
                    buf += chunk.decode("utf-8", "replace")
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
                        return parsed
        except (OSError, TimeoutError):
            return None
        return None

    @classmethod
    def _mark_after_reopen(cls, pid: int, size_before: int) -> Optional[int]:
        """The new stream shrinks the file once the tuner locks, 3 to 12 s after the command.

        Every shrink is a new start. A mark taken before it never grows back.
        """
        low = prev = size_before
        t0, s0 = 0.0, 0
        deadline = time.time() + DUMP_WAIT_SECS
        while time.time() < deadline:
            if not cls._pid_alive(pid):
                return None
            size = cls.dump_bytes()
            if size + TS_PACKET < prev:
                low = size
                t0, s0 = time.time(), size
            elif size > low and not t0:
                t0, s0 = time.time(), size
            prev = size
            if size >= align_ts(low) + MIN_PLAYABLE_BYTES:
                cls._note_open_rate(t0, s0, size)
                return align_ts(low)
            time.sleep(0.05)
        return None

    @classmethod
    def _retune_running_dump(cls, name: str) -> bool:
        """Point the live dump at another station without a new mpv.

        Setting dvbin-prog closes the stream. This mpv locks again for every
        station, including a subchannel on the same tower.
        """
        state = cls.load_state()
        pid = int(state.get("pid") or 0)
        if not cls._pid_alive(pid):
            return False
        origin = str(state.get("switching_from") or "")
        current = origin or str(state.get("tune_name") or state.get("channel") or "")
        if not origin and current == name:
            return False
        # A filtered dump has no video PID for a 0:0 row. That one still restarts.
        if cls._conf_needs_full_mux(name) and not state.get("full_mux"):
            return False
        size_before = cls.dump_bytes()
        cls.patch_state(channel=name, tune_name=name)
        reply = cls._dump_command(["set_property", "dvbin-prog", name])
        if not reply or reply.get("error") != "success":
            return False
        # This mpv closes the stream and locks again. The file usually shrinks.
        # The mark has to be that new start, not the size from before the close.
        cls._open_bps = 0.0
        mark = cls._mark_after_reopen(pid, size_before)
        if mark is None:
            return False
        cls.patch_state(
            channel=name,
            tune_name=name,
            running=True,
            open_bps=cls._open_bps,
            play_from=mark,
            view="live",
            paused=False,
            playhead_byte=mark,
            playhead_t=0,
            switching_from="",
        )
        return True

    @classmethod
    def _spawn_dump(
        cls,
        name: str,
        adapter_id: int,
        dest: str,
        sock: str,
        log_name: str = "dump.log",
    ) -> Optional[subprocess.Popen]:
        cls.ensure_dir()
        if os.path.exists(sock):
            try:
                os.unlink(sock)
            except OSError:
                pass
        touch_private_file(dest)
        log_path = os.path.join(TIMESHIFT_DIR, log_name)
        touch_private_file(log_path)
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
        ]
        # A 0:0 row, or a video id copied from another service, has no
        # picture of its own. The whole tower still does.
        if cls._conf_needs_full_mux(name):
            cmd.append("--dvbin-full-transponder=yes")
        cmd.append(f"dvb://{name}")
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        if isinstance(proc.poll(), int):
            return None
        chmod_private_file(dest)
        chmod_private_file(log_path)
        return proc

    @classmethod
    def _wait_dump_playable(cls, proc: subprocess.Popen, dest: str, log_path: Optional[str] = None) -> bool:
        deadline = time.time() + DUMP_WAIT_SECS
        last_size = 0
        next_note = 0.0
        t0, s0 = 0.0, 0
        cls._open_bps = 0.0
        while time.time() < deadline:
            if isinstance(proc.poll(), int):
                return False
            now = time.time()
            if log_path and now >= next_note:
                next_note = now + 0.4
                snr = cls._snr_db_from_log(log_path)
                if snr is not None:
                    cls.patch_tune_status(snr_db=snr)
            try:
                size = os.path.getsize(dest) if os.path.isfile(dest) else 0
            except OSError:
                size = 0
            # The first bytes are the lock. The rate counts from there.
            if size > 0 and not t0:
                t0, s0 = time.time(), size
            if size >= MIN_PLAYABLE_BYTES:
                cls._note_open_rate(t0, s0, size)
                chmod_private_file(dest)
                if log_path:
                    chmod_private_file(log_path)
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
        """Locks tuner 0, dumps dvb:// into live.ts, waits until the file is playable.

        keep_follow: channel change under a live PiP. Stop the dump, replace
        live.ts, leave the reader. The player loadfiles the same fifo.
        """
        name = (tune_name or "").strip()
        if not name:
            return None

        from engine import pool

        held = pool.claims()
        if adapter_id is None:
            adapter_id = pool.pick_live(held)
        if held.get(adapter_id) == "guide":
            pool.ask_guide_to_yield(adapter_id)

        follow_pid = 0
        follow_socket = FOLLOW_SOCKET_PATH
        if keep_follow:
            state = cls.load_state()
            follow_pid = int(state.get("follow_pid") or 0)
            follow_socket = str(state.get("follow_socket") or FOLLOW_SOCKET_PATH)
            cls.stop_dump(keep_follow=True)
            cls._retire_dump_file()
            cls.ensure_dir()
        else:
            cls.wipe()
            cls.ensure_dir()

        cls._reap_orphan_dumps()
        # A Guide tower asked to yield lets go within a second or two.
        cls._wait_frontend_free(timeout=4.0 if held.get(adapter_id) == "guide" else 0.8, adapter_id=adapter_id)
        sock = TIMESHIFT_SOCKET_PATH
        proc = cls._capture_dump(name, adapter_id, TIMESHIFT_FILE, sock, "dump.log")
        pool.clear_yield()
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
            "play_from": 0,
            "full_mux": cls._conf_needs_full_mux(name),
            "open_bps": cls._open_bps,
            "started_at": time.time(),
            "updated_at": time.time(),
        }
        if keep_follow and follow_pid:
            payload["follow_pid"] = follow_pid
            payload["follow_socket"] = follow_socket
        cls._write_state(payload)
        return TIMESHIFT_FILE

    @classmethod
    def note_channel(cls, tune_name: str) -> bool:
        """Write the clicked station before the lock, so the banner can show it.

        Same station, a dead dump, or a whole-tower target on a filtered dump stays quiet.
        """
        name = (tune_name or "").strip()
        if not name:
            return False
        state = cls.load_state()
        pid = int(state.get("pid") or 0)
        if not cls._pid_alive(pid):
            return False
        current = str(state.get("tune_name") or state.get("channel") or "")
        if current == name:
            return False
        if cls._conf_needs_full_mux(name) and not state.get("full_mux"):
            return False
        cls.patch_state(channel=name, tune_name=name, switching_from=current)
        return True

    @classmethod
    def retune_keep_window(cls, tune_name: str) -> Optional[str]:
        """Reuse the live dump on its tuner. This mpv locks again for every station.

        The picture opens at play_from. Picking the same station again still
        starts a fresh dump.
        """
        name = (tune_name or "").strip()
        if name and cls._retune_running_dump(name):
            return TIMESHIFT_FILE
        return cls.start_dump(name, keep_follow=True)
