"""
Yagi - ATSC Frequency Scanner & Channel Discovery Engine
Tunes each physical channel and reads PAT, PMT, and the virtual channel table.
"""

import contextlib
import errno
import os
import json
import time
from typing import List, Dict, Generator, Any, Optional, Callable, Tuple
from engine import pool
from engine.tuner import TunerManager
from engine.paths import CHANNELS_JSON_PATH, MPV_CHANNELS_CONF, SCAN_STATUS_PATH, state_lock


RECORDING_BUSY = "Tuner busy: a recording is using it"
STOPPED_EARLY = "Scan stopped before it finished."


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def scan_stop_reason(exc: BaseException) -> str:
    """Plain reason a scan did not finish."""
    if isinstance(exc, KeyboardInterrupt):
        return "Scan stopped."
    if isinstance(exc, OSError) and exc.errno == errno.EBUSY:
        return RECORDING_BUSY
    text = str(exc).strip()
    if text:
        return f"Scan stopped: {text}"
    return STOPPED_EARLY


def read_scan_status(status_path: Optional[str] = None) -> Dict[str, Any]:
    """The scan status. A scan whose process is gone is recorded as stopped."""
    target = status_path or SCAN_STATUS_PATH
    try:
        with open(target, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    if data.get("is_scanning") and not _pid_alive(int(data.get("pid") or 0)):
        data = dict(data)
        data["status"] = "error"
        data["is_scanning"] = False
        data["message"] = STOPPED_EARLY
        write_scan_status(data, status_path=target)
    return data


def write_scan_status(status_dict: Dict[str, Any], status_path: Optional[str] = None) -> None:
    """Writes scan progress atomically for Quickshell UI."""
    target_path = status_path or SCAN_STATUS_PATH
    try:
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        tmp = target_path + ".tmp"
        payload = dict(status_dict)
        if "updated_at" not in payload:
            payload["updated_at"] = time.time()
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, target_path)
    except Exception:
        pass


def _write_text_atomic(path: str, text: str) -> None:
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


# A locked tower is read at least this long, so PAT, PMT, and the virtual channel table are in the capture.
SCAN_DWELL_SEC = 1.2
# The first tune after the frontend opens, then each later lock, fits in this.
SCAN_LOCK_SEC = 4.0


def first_pid(value: Any) -> int:
    """First PID when a field lists several, like '52 53'."""
    text = str("" if value is None else value).strip()
    if not text:
        return 0
    try:
        return int(text.split()[0])
    except ValueError:
        return 0


# North American ATSC Standard Frequencies
def get_atsc_frequencies(quick_mode: bool = False) -> List[Dict[str, Any]]:
    """
    Returns list of ATSC physical channels and frequencies.
    Uses exact +28615 Hz ATSC pilot carrier offsets for instant demodulator lock.
    """
    channels = []

    if not quick_mode:
        # VHF-Low: Channels 2-6
        vhf_low = [
            (2, 57028615),
            (3, 63028615),
            (4, 69028615),
            (5, 79028615),
            (6, 85028615)
        ]
        for ch, freq in vhf_low:
            channels.append({"channel": ch, "frequency": freq, "band": "VHF-Low"})

    # VHF-High: Channels 7-13
    for ch in range(7, 14):
        freq = 177028615 + (ch - 7) * 6000000
        channels.append({"channel": ch, "frequency": freq, "band": "VHF-High"})

    # Core UHF: Channels 14-36 (Post-Incentive Auction Repack standard)
    for ch in range(14, 37):
        freq = 473028615 + (ch - 14) * 6000000
        channels.append({"channel": ch, "frequency": freq, "band": "UHF"})

    if not quick_mode:
        # Legacy UHF: Channels 37-69
        for ch in range(37, 70):
            freq = 611028615 + (ch - 37) * 6000000
            channels.append({"channel": ch, "frequency": freq, "band": "UHF-Extended"})

    return channels


def _pat_programs(sections: List[bytes]) -> Dict[int, int]:
    """Program number to its PMT pid, from the PAT."""
    found: Dict[int, int] = {}
    for section in sections:
        if not section or section[0] != 0x00 or len(section) < 12:
            continue
        for i in range(8, len(section) - 7, 4):
            program = (section[i] << 8) | section[i + 1]
            pid = ((section[i + 2] & 0x1F) << 8) | section[i + 3]
            if program > 0 and pid > 0:
                found[program] = pid
    return found


def _virtual_by_program(sections: List[bytes]) -> Dict[int, Dict[str, Any]]:
    from engine.psip import TABLE_TVCT, parse_tvct_rows

    found: Dict[int, Dict[str, Any]] = {}
    for section in sections:
        if not section or section[0] != TABLE_TVCT:
            continue
        for row in parse_tvct_rows(section).values():
            try:
                program = int(row.get("program") or 0)
            except (TypeError, ValueError):
                continue
            if program > 0:
                found[program] = row
    return found


def parse_scan_transport(ts_data: bytes, channel: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Channel records from one tower's PAT, PMT, and virtual channel table.

    The frequency is the tuned pilot, kept as given. The first audio PID is the one stored.
    """
    from engine.psip import collect_sections, parse_pmt_pids

    if not ts_data:
        return []
    sections = collect_sections(ts_data)
    pat = _pat_programs(sections)
    pids = parse_pmt_pids(ts_data, sections)
    virtual = _virtual_by_program(sections)
    programs = sorted(set(pat) | set(pids) | set(virtual))
    # The Hz value is already the ATSC pilot. Do not round it.
    freq = int(channel.get("frequency") or 0)
    records: List[Dict[str, Any]] = []
    for program in programs:
        if program not in pids and program not in virtual:
            continue
        video, audio = pids.get(program, (0, 0))
        row = virtual.get(program) or {}
        short = str(row.get("short_name") or "").strip()
        number = str(row.get("number") or "").strip()
        if number and short:
            name = f"{number} {short}"
        elif number or short:
            name = number or short
        else:
            name = str(program)
        record: Dict[str, Any] = {
            "name": name,
            "raw_name": name,
            "service_id": int(program),
            "frequency": freq,
            "modulation": "VSB/8",
            "delivery_system": "ATSC",
            "video_pid": int(video or 0),
            "audio_pid": int(audio or 0),
            "physical_channel": channel.get("channel"),
            "band": channel.get("band") or "",
        }
        if number:
            record["id"] = number
        if short:
            record["callsign"] = short
        if row.get("major") is not None:
            record["major"] = int(row["major"])
            record["minor"] = int(row["minor"])
        records.append(record)
    return records


class AtscScanner:
    def __init__(self, adapter_id: Optional[int] = None):
        self.adapter_id = adapter_id

    def _resolve_adapter(self) -> int:
        if self.adapter_id is not None:
            return self.adapter_id
        from engine import pool
        picked = pool.pick_work(wait_for_guide=False)
        return -1 if picked is None else picked

    def _block_message(self, adapter: int) -> str:
        """Why this tuner cannot be scanned, or empty when it is free."""
        from engine import pool
        job = pool.claims().get(adapter)
        if job == "record":
            return RECORDING_BUSY
        if job == "live":
            return "Tuner busy: live TV is using it"
        if job == "guide":
            return "Tuner busy: the Guide is using it"
        if job == "scan":
            return "A scan is already running."
        if not TunerManager.adapter_is_free(adapter):
            return RECORDING_BUSY
        return ""

    def _read_channel(self, tuner, freq: int, timeout_multiplier: float) -> Tuple[bytes, Optional[float]]:
        """Lock one pilot and read the tower. The frequency is not rounded."""
        lock_for = max(SCAN_DWELL_SEC, SCAN_LOCK_SEC * float(timeout_multiplier or 1))
        dwell = max(SCAN_DWELL_SEC, SCAN_DWELL_SEC * float(timeout_multiplier or 1))
        if not tuner.tune(int(freq), lock_for):
            return b"", None
        tuner.start()
        try:
            deadline = time.monotonic() + dwell
            chunks: List[bytes] = []
            snr = None
            while time.monotonic() < deadline:
                data = tuner.read()
                if data:
                    chunks.append(data)
                else:
                    time.sleep(0.01)
                raw = tuner.snr()
                if raw is not None:
                    snr = round(raw / 10.0, 1)
            return b"".join(chunks), snr
        finally:
            tuner.stop()
            tuner.drain()

    def scan(
        self,
        quick_mode: bool = False,
        timeout_multiplier: float = 1.0,
        read_tower: Optional[Callable[[int, Dict[str, Any]], Tuple[bytes, Optional[float]]]] = None,
    ) -> Generator[Dict[str, Any], None, List[Dict[str, Any]]]:
        """
        Runs an ATSC scan, yielding real-time progress events.
        Yields dicts with keys: status, percent, channel, frequency, band, signal_dbm, total_found.
        """
        adapter = self._resolve_adapter()
        freq_list = get_atsc_frequencies(quick_mode=quick_mode)
        total_freqs = len(freq_list)

        # Held for the whole scan. Recordings, live TV, and the Guide tune under it too.
        tuner_lock = contextlib.ExitStack()
        block = ""
        try:
            if adapter < 0:
                raise TimeoutError(adapter)
            tuner_lock.enter_context(state_lock(pool.lock_key(adapter), timeout=0.5))
            block = self._block_message(adapter)
        except TimeoutError:
            held = pool.claims()
            if "record" in held.values():
                block = RECORDING_BUSY
            elif "live" in held.values():
                block = "Tuner busy: live TV is using it"
            else:
                block = pool.busy_text()
        if block:
            tuner_lock.close()
            ev_busy = {
                "status": "error",
                "is_scanning": False,
                "adapter_id": adapter,
                "message": block,
                "percent": 0,
                "total_found": 0,
            }
            write_scan_status(ev_busy)
            yield ev_busy
            return []

        ev_start = {
            "status": "starting",
            "is_scanning": True,
            "adapter_id": adapter,
            "pid": os.getpid(),
            "total_channels": total_freqs,
            "quick_mode": quick_mode,
            "percent": 0
        }
        write_scan_status(ev_start)
        yield ev_start

        discovered_channels: List[Dict[str, Any]] = []
        scan_completed = False
        stop_reason = ""
        tuner = None
        percent = 0
        try:
            if read_tower is None:
                from engine.tower_dump import Tuner
                tuner = Tuner(adapter)
            for index, info in enumerate(freq_list):
                percent = int(((index + 1) / total_freqs) * 100)
                ev_scan = {
                    "status": "scanning",
                    "is_scanning": True,
                    "pid": os.getpid(),
                    "index": index + 1,
                    "total": total_freqs,
                    "percent": percent,
                    "channel": info["channel"],
                    "frequency": info["frequency"],
                    "band": info["band"],
                    "signal_dbm": None,
                    "total_found": len(discovered_channels),
                    "channels": discovered_channels,
                }
                write_scan_status(ev_scan)
                if read_tower is not None:
                    data, snr = read_tower(adapter, info)
                else:
                    data, snr = self._read_channel(tuner, info["frequency"], timeout_multiplier)
                ev_scan["signal_dbm"] = snr
                write_scan_status(ev_scan)
                yield ev_scan
                found = parse_scan_transport(data or b"", info) if data else []
                for ch_entry in found:
                    discovered_channels.append(ch_entry)
                    ev_found = {
                        "status": "channel_found",
                        "is_scanning": True,
                        "channel": ch_entry,
                        "total_found": len(discovered_channels),
                        "percent": percent,
                        "channels": discovered_channels,
                    }
                    ev_found["pid"] = os.getpid()
                    write_scan_status(ev_found)
                    yield ev_found

            self.commit_discovered(discovered_channels)
            ev_done = {
                "status": "complete",
                "is_scanning": False,
                "percent": 100,
                "total_found": len(discovered_channels),
                "channels": discovered_channels,
            }
            scan_completed = True
            write_scan_status(ev_done)
            yield ev_done
        except GeneratorExit:
            stop_reason = STOPPED_EARLY
            raise
        except KeyboardInterrupt:
            stop_reason = "Scan stopped."
            raise
        except Exception as exc:
            stop_reason = scan_stop_reason(exc)
            raise
        finally:
            try:
                if tuner is not None:
                    tuner.close()
            except Exception:
                pass
            if not scan_completed:
                write_scan_status({
                    "status": "error",
                    "is_scanning": False,
                    "pid": os.getpid(),
                    "message": stop_reason or STOPPED_EARLY,
                    "percent": percent,
                    "total_found": len(discovered_channels),
                    "channels": discovered_channels,
                })
            tuner_lock.close()
        if scan_completed:
            return discovered_channels

    @classmethod
    def save_channels(cls, channels: List[Dict[str, Any]], json_path: Optional[str] = None, mpv_path: Optional[str] = None) -> None:
        """Replace the lineup in JSON and channels.conf. A rescan rewrites both."""
        from engine.enrichment import enrich_and_sort_channels
        enriched_channels = enrich_and_sort_channels(channels)

        target_json = json_path or CHANNELS_JSON_PATH
        target_mpv = mpv_path or MPV_CHANNELS_CONF
        os.makedirs(os.path.dirname(target_json), exist_ok=True)
        payload = {
            "updated_at": time.time(),
            "total": len(enriched_channels),
            "channels": enriched_channels
        }
        tmp_json = f"{target_json}.tmp.{os.getpid()}"
        with open(tmp_json, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp_json, target_json)

        # MPV channels.conf in ATSC format (NAME:FREQ:8VSB:VPID:APID:SID)
        conf_lines = []
        for ch in enriched_channels:
            tune_name = ch.get("tune_name") or ch.get("name", "Unknown")
            freq = ch.get("frequency", 0)
            sid = ch.get("service_id", 1)
            vpid = first_pid(ch.get("video_pid"))
            apid = first_pid(ch.get("audio_pid"))
            conf_lines.append(f"{tune_name}:{freq}:8VSB:{vpid}:{apid}:{sid}\n")
            ch_num = ch.get("channel_number")
            if ch_num and ch_num != tune_name:
                conf_lines.append(f"{ch_num}:{freq}:8VSB:{vpid}:{apid}:{sid}\n")
        conf_text = "".join(conf_lines)

        os.makedirs(os.path.dirname(target_mpv), exist_ok=True)
        _write_text_atomic(target_mpv, conf_text)
        if target_mpv == MPV_CHANNELS_CONF:
            try:
                _write_text_atomic(target_mpv + ".atsc", conf_text)
            except Exception:
                pass

        if target_json == CHANNELS_JSON_PATH:
            try:
                from engine.guide import sync_guide_from_channels
                sync_guide_from_channels(enriched_channels)
            except Exception:
                pass

    @classmethod
    def commit_discovered(cls, channels: List[Dict[str, Any]], json_path: Optional[str] = None, mpv_path: Optional[str] = None) -> bool:
        """Write a scan result. An empty result leaves the saved lineup alone."""
        if not channels:
            return False
        cls.save_channels(channels, json_path=json_path, mpv_path=mpv_path)
        return True


if __name__ == "__main__":
    scanner = AtscScanner()
    print("Starting fast ATSC scan...")
    for event in scanner.scan(quick_mode=True):
        if event["status"] == "scanning":
            sig = f"{event['signal_dbm']:.1f} dB" if event['signal_dbm'] else "No Lock"
            print(f"[{event['percent']:3d}%] Ch {event['channel']:2d} ({event['band']:8s}) - Signal: {sig} (Found: {event['total_found']})")
        elif event["status"] == "channel_found":
            print(f"  >>> FOUND CHANNEL: {event['channel']['name']}")
        elif event["status"] == "complete":
            print(f"\nScan complete! Discovered {event['total_found']} channels.")
