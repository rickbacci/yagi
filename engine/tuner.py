"""
Omarchy TV - Tuner Hardware Manager
Detects, queries, and allocates Linux DVB adapters for ATSC OTA television.
"""

import fcntl
import glob
import os
import subprocess
from typing import List, Dict, Optional, Any, Set

# linux/dvb/frontend.h _IOR('o', nr, size). SNR on this stick is tenths of a dB.
_FE_READ_STATUS = (2 << 30) | (4 << 16) | (ord("o") << 8) | 69
_FE_READ_SIGNAL_STRENGTH = (2 << 30) | (2 << 16) | (ord("o") << 8) | 71
_FE_READ_SNR = (2 << 30) | (2 << 16) | (ord("o") << 8) | 72
_FE_HAS_LOCK = 0x10

# DualHD jobs: 0 is the picture, 1 is scan / Guide / library record.
LIVE_ADAPTER = 0
WORK_ADAPTER = 1


def decode_frontend(status: int, strength: Optional[int], snr_raw: Optional[int]) -> Dict[str, Any]:
    """Turn a frontend reading into lock, dB, and a strength percent."""
    snr_db = None if snr_raw is None else round(snr_raw / 10.0, 1)
    pct = None if strength is None else round(100.0 * strength / 65535.0, 1)
    return {
        "locked": bool(status & _FE_HAS_LOCK),
        "snr_db": snr_db,
        "strength": strength,
        "strength_pct": pct,
    }


class TunerAdapter:
    def __init__(self, adapter_id: int):
        self.adapter_id = adapter_id
        self.path = f"/dev/dvb/adapter{adapter_id}"
        self.frontend_path = f"{self.path}/frontend0"
        self.demux_path = f"{self.path}/demux0"
        self.dvr_path = f"{self.path}/dvr0"
        self.name = "Unknown DVB Adapter"
        self.delivery_systems: List[str] = []
        self.current_system = "Unknown"
        self._inspect()

    def _inspect(self):
        """Query frontend capabilities using dvb-fe-tool."""
        if not os.path.exists(self.frontend_path):
            return

        try:
            res = subprocess.run(
                ["dvb-fe-tool", "-a", str(self.adapter_id)],
                capture_output=True,
                text=True,
                timeout=3
            )
            for line in res.stdout.splitlines():
                line_s = line.strip()
                if "Device " in line and "Frontend" in line:
                    # Extract device name
                    parts = line_s.split("Device ", 1)[-1].split(" (", 1)
                    if parts:
                        self.name = parts[0].strip()
                elif "Current v5 delivery system:" in line:
                    self.current_system = line.split(":", 1)[-1].strip()
                elif line_s in ("ATSC", "DVBC/ANNEX_B", "DVBT", "DVBT2", "ISDBT"):
                    if line_s not in self.delivery_systems:
                        self.delivery_systems.append(line_s)
                elif line_s.startswith("[") and line_s.endswith("]"):
                    sys_name = line_s.strip("[] ")
                    if sys_name not in self.delivery_systems:
                        self.delivery_systems.append(sys_name)
        except Exception:
            pass

    @property
    def supports_atsc(self) -> bool:
        return "ATSC" in self.delivery_systems or self.current_system == "ATSC"

    @property
    def is_busy(self) -> bool:
        """Check if frontend device is currently opened by another process."""
        if not os.path.exists(self.frontend_path):
            return True
        try:
            res = subprocess.run(
                ["fuser", self.frontend_path],
                capture_output=True,
                timeout=1
            )
            # fuser returns returncode 0 if files are open
            return res.returncode == 0
        except FileNotFoundError:
            return False
        except Exception:
            return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "path": self.path,
            "frontend": self.frontend_path,
            "name": self.name,
            "current_system": self.current_system,
            "delivery_systems": self.delivery_systems,
            "supports_atsc": self.supports_atsc,
            "is_busy": self.is_busy
        }


class TunerManager:
    """Manages multi-tuner allocation (e.g. dual tuners)."""

    @classmethod
    def list_tuners(cls) -> List[TunerAdapter]:
        adapters = []
        for path in sorted(glob.glob("/dev/dvb/adapter*")):
            try:
                adapter_id = int(path.replace("/dev/dvb/adapter", ""))
                adapters.append(TunerAdapter(adapter_id))
            except ValueError:
                continue
        return adapters

    @classmethod
    def read_signal(cls, adapter_id: int = LIVE_ADAPTER) -> Optional[Dict[str, Any]]:
        """SNR and strength for a frontend that is already tuned. None if it is missing."""
        path = f"/dev/dvb/adapter{adapter_id}/frontend0"
        if not os.path.exists(path):
            return None
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            return None
        try:
            status_buf = bytearray(4)
            try:
                fcntl.ioctl(fd, _FE_READ_STATUS, status_buf, True)
            except OSError:
                return decode_frontend(0, None, None)
            strength = None
            snr_raw = None
            strength_buf = bytearray(2)
            snr_buf = bytearray(2)
            try:
                fcntl.ioctl(fd, _FE_READ_SIGNAL_STRENGTH, strength_buf, True)
                strength = int.from_bytes(strength_buf, "little")
            except OSError:
                pass
            try:
                fcntl.ioctl(fd, _FE_READ_SNR, snr_buf, True)
                snr_raw = int.from_bytes(snr_buf, "little")
            except OSError:
                pass
            return decode_frontend(int.from_bytes(status_buf, "little"), strength, snr_raw)
        finally:
            os.close(fd)

    @classmethod
    def get_adapter(cls, adapter_id: int) -> Optional[TunerAdapter]:
        for tuner in cls.list_tuners():
            if tuner.adapter_id == adapter_id:
                return tuner
        return None

    @classmethod
    def adapter_is_free(cls, adapter_id: int, require_atsc: bool = True) -> bool:
        """True when that numbered frontend exists, is ATSC, and fuser is clear."""
        path = f"/dev/dvb/adapter{adapter_id}/frontend0"
        if not os.path.exists(path):
            return False
        tuner = TunerAdapter(adapter_id)
        if require_atsc and not tuner.supports_atsc:
            return False
        return not tuner.is_busy

    @classmethod
    def get_available_tuner(cls, require_atsc: bool = True, exclude_adapters: Optional[Set[int]] = None) -> Optional[TunerAdapter]:
        """Returns the first non-busy tuner that matches criteria, excluding any specified adapters."""
        exclude = exclude_adapters or set()
        for tuner in cls.list_tuners():
            if tuner.adapter_id in exclude:
                continue
            if require_atsc and not tuner.supports_atsc:
                continue
            if not tuner.is_busy:
                return tuner
        return None


if __name__ == "__main__":
    manager = TunerManager()
    tuners = manager.list_tuners()
    print(f"Discovered {len(tuners)} tuner adapters:")
    for t in tuners:
        info = t.to_dict()
        status = "BUSY" if info["is_busy"] else "FREE"
        print(f"  [{info['adapter_id']}] {info['name']} ({status}) - Systems: {info['delivery_systems']}")
