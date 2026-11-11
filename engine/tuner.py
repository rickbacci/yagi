"""
Yagi - Tuner Hardware Manager
Detects, queries, and allocates Linux DVB adapters for ATSC OTA television.
"""

import ctypes
import fcntl
import glob
import os
import struct
from typing import List, Dict, Optional, Any, Set

# linux/dvb/frontend.h _IOR('o', nr, size). SNR on this stick is tenths of a dB.
_FE_READ_STATUS = (2 << 30) | (4 << 16) | (ord("o") << 8) | 69
_FE_READ_SIGNAL_STRENGTH = (2 << 30) | (2 << 16) | (ord("o") << 8) | 71
_FE_READ_SNR = (2 << 30) | (2 << 16) | (ord("o") << 8) | 72
_FE_GET_INFO = (2 << 30) | (168 << 16) | (ord("o") << 8) | 61
_FE_GET_PROPERTY = (2 << 30) | (16 << 16) | (ord("o") << 8) | 83
_DTV_DELIVERY_SYSTEM = 17
_DTV_ENUM_DELSYS = 44
_FE_ATSC = 3
_INFO_LEN = 168
_FE_HAS_LOCK = 0x10

# Names the rest of the app already checks. SYS_ATSC is 11.
_DELIVERY_NAMES = {
    1: "DVBC/ANNEX_A",
    2: "DVBC/ANNEX_B",
    3: "DVBT",
    5: "DVBS",
    6: "DVBS2",
    8: "ISDBT",
    11: "ATSC",
    16: "DVBT2",
    18: "DVBC/ANNEX_C",
    19: "DVBC2",
}

# DualHD jobs: 0 is the picture, 1 is scan / Guide / library record.
LIVE_ADAPTER = 0
WORK_ADAPTER = 1


def _dtv_property(cmd: int) -> bytes:
    """struct dtv_property, packed the same way the live dump packs a tune."""
    return struct.pack("<I12xI52xi", int(cmd), 0, 0)


def _get_property(fd: int, cmd: int) -> Optional[bytes]:
    raw = ctypes.create_string_buffer(_dtv_property(cmd))
    try:
        fcntl.ioctl(fd, _FE_GET_PROPERTY, struct.pack("<I4xQ", 1, ctypes.addressof(raw)))
    except OSError:
        return None
    return raw.raw


def _delivery_systems(fd: int) -> List[str]:
    blob = _get_property(fd, _DTV_ENUM_DELSYS)
    if not blob or len(blob) < 52:
        return []
    count = max(0, min(8, struct.unpack_from("<I", blob, 48)[0]))
    names: List[str] = []
    for i in range(count):
        value = struct.unpack_from("<I", blob, 16 + i * 4)[0]
        name = _DELIVERY_NAMES.get(value)
        if name and name not in names:
            names.append(name)
    return names


def _current_system(fd: int) -> str:
    blob = _get_property(fd, _DTV_DELIVERY_SYSTEM)
    if not blob or len(blob) < 20:
        return ""
    return _DELIVERY_NAMES.get(struct.unpack_from("<I", blob, 16)[0], "")


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
        """Name and delivery systems from FE_GET_INFO and DTV_ENUM_DELSYS."""
        if not os.path.exists(self.frontend_path):
            return
        try:
            fd = os.open(self.frontend_path, os.O_RDWR | os.O_NONBLOCK)
        except OSError:
            return
        try:
            info = bytearray(_INFO_LEN)
            try:
                fcntl.ioctl(fd, _FE_GET_INFO, info, True)
            except OSError:
                info = b""
            if info:
                name = bytes(info[:128]).split(b"\x00", 1)[0].decode("utf-8", "replace").strip()
                if name:
                    self.name = name
            systems = _delivery_systems(fd)
            for name in systems:
                if name not in self.delivery_systems:
                    self.delivery_systems.append(name)
            current = _current_system(fd)
            if current:
                self.current_system = current
            elif info and struct.unpack_from("<I", info, 128)[0] == _FE_ATSC and "ATSC" not in self.delivery_systems:
                self.delivery_systems.append("ATSC")
                self.current_system = "ATSC"
        finally:
            os.close(fd)

    @property
    def supports_atsc(self) -> bool:
        return "ATSC" in self.delivery_systems or self.current_system == "ATSC"

    @property
    def is_busy(self) -> bool:
        """True when opening the frontend returns EBUSY, or it cannot be opened.

        fuser is not used here. The library size cap is what still asks fuser,
        and a missing fuser there still means the file is treated as busy.
        """
        if not os.path.exists(self.frontend_path):
            return True
        try:
            fd = os.open(self.frontend_path, os.O_RDWR | os.O_NONBLOCK)
        except OSError:
            # EBUSY is a frontend someone else holds. Any other open failure is not a free tuner.
            return True
        os.close(fd)
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
        """True when that numbered frontend exists, is ATSC, and opens without EBUSY."""
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
