"""
Omarchy TV - Tuner Hardware Manager
Detects, queries, and allocates Linux DVB adapters for ATSC OTA television.
"""

import os
import glob
import subprocess
from typing import List, Dict, Optional, Any


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
        except Exception:
            return False

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
    def get_available_tuner(cls, require_atsc: bool = True) -> Optional[TunerAdapter]:
        """Returns the first non-busy tuner that matches criteria."""
        for tuner in cls.list_tuners():
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
