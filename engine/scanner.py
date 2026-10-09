"""
Yagi - ATSC Frequency Scanner & Channel Discovery Engine
Performs fast, intelligent OTA broadcast scanning with real-time JSON progress.
"""

import contextlib
import os
import sys
import json
import time
import tempfile
import subprocess
from typing import List, Dict, Generator, Any, Optional
from engine import pool
from engine.tuner import TunerManager
from engine.paths import CHANNELS_JSON_PATH, MPV_CHANNELS_CONF, SCAN_STATUS_PATH, state_lock


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


def generate_scan_conf(channels: List[Dict[str, Any]]) -> str:
    """Generate DVBv5 initial configuration file content."""
    lines = []
    for ch in channels:
        lines.append(f"[CH_{ch['channel']}]")
        lines.append("  DELIVERY_SYSTEM = ATSC")
        lines.append(f"  FREQUENCY = {ch['frequency']}")
        lines.append("  MODULATION = VSB/8")
        lines.append("")
    return "\n".join(lines)


class AtscScanner:
    def __init__(self, adapter_id: Optional[int] = None):
        self.adapter_id = adapter_id

    def _resolve_adapter(self) -> int:
        if self.adapter_id is not None:
            return self.adapter_id
        from engine import pool
        picked = pool.pick_work(wait_for_guide=False)
        return -1 if picked is None else picked

    def _work_tuner_ready(self, adapter: int) -> bool:
        from engine import pool
        if adapter in pool.claims():
            return False
        return TunerManager.adapter_is_free(adapter)

    def scan(self, quick_mode: bool = False, timeout_multiplier: float = 1.0) -> Generator[Dict[str, Any], None, List[Dict[str, Any]]]:
        """
        Runs ATSC scan, yielding real-time progress events.
        Yields dicts with keys: phase, percent, channel, frequency, band, signal_dbm, channels_found
        """
        adapter = self._resolve_adapter()
        freq_list = get_atsc_frequencies(quick_mode=quick_mode)
        total_freqs = len(freq_list)

        # Held for the whole scan. Recordings, live TV, and the Guide tune under it too.
        tuner_lock = contextlib.ExitStack()
        try:
            if adapter < 0:
                raise TimeoutError(adapter)
            tuner_lock.enter_context(state_lock(pool.lock_key(adapter), timeout=0.5))
            ready = self._work_tuner_ready(adapter)
        except TimeoutError:
            ready = False
        if not ready:
            tuner_lock.close()
            ev_busy = {
                "status": "error",
                "is_scanning": False,
                "adapter_id": adapter,
                "message": pool.busy_text(),
                "percent": 0,
            }
            write_scan_status(ev_busy)
            yield ev_busy
            return []

        ev_start = {
            "status": "starting",
            "is_scanning": True,
            "adapter_id": adapter,
            "total_channels": total_freqs,
            "quick_mode": quick_mode,
            "percent": 0
        }
        write_scan_status(ev_start)
        yield ev_start

        # Write temp initial config file
        with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as f_in:
            f_in.write(generate_scan_conf(freq_list))
            in_conf_path = f_in.name

        with tempfile.NamedTemporaryFile("w", suffix=".conf", delete=False) as f_out:
            out_conf_path = f_out.name

        cmd = [
            "dvbv5-scan",
            "-v",
            "-a", str(adapter),
            "-T", str(timeout_multiplier),
            "-o", out_conf_path,
            in_conf_path
        ]

        discovered_channels: List[Dict[str, Any]] = []
        current_freq_index = 0
        current_signal: Optional[float] = None
        scan_completed = False
        proc = None

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            for line in proc.stdout:
                line_s = line.strip()
                if not line_s:
                    continue

                # Parse frequency transition: "Scanning frequency #X YYYYY"
                if "Scanning frequency #" in line_s:
                    try:
                        parts = line_s.split("Scanning frequency #", 1)[-1].split()
                        current_freq_index = int(parts[0]) - 1
                    except (ValueError, IndexError):
                        pass

                    cur_info = freq_list[min(current_freq_index, total_freqs - 1)]
                    percent = int(((current_freq_index + 1) / total_freqs) * 100)
                    ev_scan = {
                        "status": "scanning",
                        "is_scanning": True,
                        "index": current_freq_index + 1,
                        "total": total_freqs,
                        "percent": percent,
                        "channel": cur_info["channel"],
                        "frequency": cur_info["frequency"],
                        "band": cur_info["band"],
                        "signal_dbm": current_signal,
                        "total_found": len(discovered_channels),
                        "channels": discovered_channels
                    }
                    write_scan_status(ev_scan)
                    yield ev_scan

                # Parse Signal strength: "Signal= -XX.XXdBm"
                if "Signal=" in line_s:
                    try:
                        sig_part = line_s.split("Signal=", 1)[-1].split("dBm")[0].strip()
                        current_signal = float(sig_part)
                    except ValueError:
                        pass

                # Parse ATSC virtual channel: "Virtual channel 53.1, name = Daystar"
                if "Virtual channel " in line_s:
                    try:
                        parts = line_s.split("Virtual channel ", 1)[-1].split(",", 1)
                        vch_num = parts[0].strip()
                        vch_name = parts[1].split("name =", 1)[-1].strip() if len(parts) > 1 and "name =" in parts[1] else vch_num
                        full_name = f"{vch_num} {vch_name}" if vch_name != vch_num else vch_num
                        if not any(c.get("id") == vch_num or c.get("name") == full_name for c in discovered_channels):
                            cur_info = freq_list[min(current_freq_index, total_freqs - 1)]
                            ch_entry = {
                                "id": vch_num,
                                "name": full_name,
                                "callsign": vch_name,
                                "physical_channel": cur_info["channel"],
                                "frequency": cur_info["frequency"],
                                "band": cur_info["band"]
                            }
                            discovered_channels.append(ch_entry)
                            ev_found = {
                                "status": "channel_found",
                                "is_scanning": True,
                                "channel": ch_entry,
                                "total_found": len(discovered_channels),
                                "percent": int(((current_freq_index + 1) / total_freqs) * 100),
                                "channels": discovered_channels
                            }
                            write_scan_status(ev_found)
                            yield ev_found
                    except Exception:
                        pass

                # Parse generic found service: "Service NAME, Provider PROVIDER"
                if "Service " in line_s and "," in line_s:
                    try:
                        name_part = line_s.split("Service ", 1)[-1].split(",")[0].strip()
                        if name_part and not any(c.get("name") == name_part for c in discovered_channels):
                            cur_info = freq_list[min(current_freq_index, total_freqs - 1)]
                            ch_entry = {
                                "id": name_part,
                                "name": name_part,
                                "callsign": name_part,
                                "physical_channel": cur_info["channel"],
                                "frequency": cur_info["frequency"],
                                "band": cur_info["band"]
                            }
                            discovered_channels.append(ch_entry)
                            ev_found = {
                                "status": "channel_found",
                                "is_scanning": True,
                                "channel": ch_entry,
                                "total_found": len(discovered_channels),
                                "percent": int(((current_freq_index + 1) / total_freqs) * 100),
                                "channels": discovered_channels
                            }
                            write_scan_status(ev_found)
                            yield ev_found
                    except Exception:
                        pass

            proc.wait()

            # Only dvbv5-scan's finished output has service ids and PIDs. The
            # progress lines above are stubs, and an empty result must not
            # erase a lineup already saved.
            discovered_channels = self._parse_scan_output(out_conf_path)
            self.commit_discovered(discovered_channels)

            ev_done = {
                "status": "complete",
                "is_scanning": False,
                "percent": 100,
                "total_found": len(discovered_channels),
                "channels": discovered_channels
            }
            write_scan_status(ev_done)
            yield ev_done
            scan_completed = True

            return discovered_channels

        finally:
            if not scan_completed and proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=3)
                except Exception:
                    try:
                        proc.kill()
                        proc.wait(timeout=3)
                    except Exception:
                        pass
            if not scan_completed:
                write_scan_status({
                    "status": "idle",
                    "is_scanning": False,
                    "percent": 0,
                    "total_found": len(discovered_channels),
                    "channels": discovered_channels
                })
            if os.path.exists(in_conf_path):
                try:
                    os.unlink(in_conf_path)
                except OSError:
                    pass
            if os.path.exists(out_conf_path):
                try:
                    os.unlink(out_conf_path)
                except OSError:
                    pass
            tuner_lock.close()

    def _parse_scan_output(self, conf_path: str) -> List[Dict[str, Any]]:
        """Parses DVBv5 channel scan output into structured channel records."""
        if not os.path.exists(conf_path):
            return []

        channels = []
        current = None

        with open(conf_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line_s = line.strip()
                if not line_s:
                    continue
                if line_s.startswith("[") and line_s.endswith("]"):
                    if current and "name" in current:
                        channels.append(current)
                    name = line_s.strip("[]")
                    current = {"name": name, "raw_name": name}
                elif "=" in line_s and current is not None:
                    k, v = line_s.split("=", 1)
                    k = k.strip().upper()
                    v = v.strip()
                    if k == "SERVICE_ID":
                        current["service_id"] = int(v) if v.isdigit() else v
                    elif k == "FREQUENCY":
                        current["frequency"] = int(v) if v.isdigit() else v
                    elif k == "MODULATION":
                        current["modulation"] = v
                    elif k == "DELIVERY_SYSTEM":
                        current["delivery_system"] = v
                    elif k == "VIDEO_PID":
                        current["video_pid"] = int(v) if v.isdigit() else v
                    elif k == "AUDIO_PID":
                        current["audio_pid"] = int(v) if v.isdigit() else v

        if current and "name" in current:
            channels.append(current)

        return channels

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
            vpid_raw = ch.get("video_pid", 0)
            apid_raw = ch.get("audio_pid", 0)
            vpid = int(str(vpid_raw).split()[0]) if vpid_raw else 0
            apid = int(str(apid_raw).split()[0]) if apid_raw else 0
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
            sig = f"{event['signal_dbm']:.1f} dBm" if event['signal_dbm'] else "No Lock"
            print(f"[{event['percent']:3d}%] Ch {event['channel']:2d} ({event['band']:8s}) - Signal: {sig} (Found: {event['total_found']})")
        elif event["status"] == "channel_found":
            print(f"  >>> FOUND CHANNEL: {event['channel']['name']}")
        elif event["status"] == "complete":
            print(f"\nScan complete! Discovered {event['total_found']} channels.")
