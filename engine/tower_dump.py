"""
Copy one tuner's whole tower into live.ts, and retune it without letting go.

mpv's dvbin closes the frontend on every station change. This tuner then takes
about a second to wake and mpv's lock wait adds more. Here the frontend stays
open for the whole session, so another tower is one DTV_TUNE and its lock.

The control socket takes one JSON line per connection, the same shape as mpv
IPC: {"command": ["tune", <Hz>]} truncates live.ts, locks the new tower, and
replies {"data": {"mark": 0}}; ["quit"] stops. SNR lines in the log use the
tuner's own tenths of a dB, which is what Timeshift._snr_db_from_log reads.

Usage: tower_dump.py ADAPTER FREQUENCY DEST SOCKET LOG
"""

from __future__ import annotations

import ctypes
import errno
import fcntl
import json
import os
import select
import signal
import socket
import struct
import sys
import time
from typing import List, Optional, Tuple

DTV_TUNE = 1
DTV_CLEAR = 2
DTV_FREQUENCY = 3
DTV_MODULATION = 4
DTV_INVERSION = 6
DTV_DELIVERY_SYSTEM = 17
SYS_ATSC = 11
VSB_8 = 7
INVERSION_AUTO = 2
FE_HAS_LOCK = 0x10

DMX_IN_FRONTEND = 0
DMX_OUT_TS_TAP = 2
DMX_PES_OTHER = 20
ALL_PIDS = 0x2000


def _ioc(direction: int, nr: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (ord("o") << 8) | nr


FE_READ_STATUS = _ioc(2, 69, 4)
FE_READ_SNR = _ioc(2, 72, 2)
FE_SET_PROPERTY = _ioc(1, 82, 16)
DMX_START = _ioc(0, 41, 0)
DMX_STOP = _ioc(0, 42, 0)
DMX_SET_PES_FILTER = _ioc(1, 44, 20)
DMX_SET_BUFFER_SIZE = _ioc(0, 45, 0)

LOCK_TIMEOUT_SEC = 15.0
DVR_BUFFER_BYTES = 8 * 1024 * 1024
READ_BYTES = 1024 * 1024
SIGNAL_EVERY_SEC = 1.0


def dtv_property(cmd: int, data: int = 0) -> bytes:
    """struct dtv_property, packed: cmd, 3 reserved, a 56-byte union, result."""
    return struct.pack("<I12xI52xi", cmd, data, 0)


def atsc_props(freq: int) -> List[Tuple[int, int]]:
    return [
        (DTV_DELIVERY_SYSTEM, SYS_ATSC),
        (DTV_FREQUENCY, int(freq)),
        (DTV_MODULATION, VSB_8),
        (DTV_INVERSION, INVERSION_AUTO),
        (DTV_TUNE, 0),
    ]


def whole_tower_filter(flags: int = 0) -> bytes:
    """struct dmx_pes_filter_params: every PID, as TS, to dvr0."""
    return struct.pack("<HxxiiiI", ALL_PIDS, DMX_IN_FRONTEND, DMX_OUT_TS_TAP, DMX_PES_OTHER, flags)


class Tuner:
    """One adapter's frontend, demux, and dvr, held open until close."""

    def __init__(self, adapter: int):
        base = f"/dev/dvb/adapter{int(adapter)}"
        self.fe = os.open(f"{base}/frontend0", os.O_RDWR | os.O_NONBLOCK)
        self.demux = os.open(f"{base}/demux0", os.O_RDWR | os.O_NONBLOCK)
        fcntl.ioctl(self.demux, DMX_SET_PES_FILTER, whole_tower_filter())
        self.dvr = os.open(f"{base}/dvr0", os.O_RDONLY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(self.dvr, DMX_SET_BUFFER_SIZE, DVR_BUFFER_BYTES)
        except OSError:
            pass

    def _set(self, pairs: List[Tuple[int, int]]) -> None:
        raw = ctypes.create_string_buffer(b"".join(dtv_property(c, d) for c, d in pairs))
        fcntl.ioctl(self.fe, FE_SET_PROPERTY, struct.pack("<I4xQ", len(pairs), ctypes.addressof(raw)))

    def tune(self, freq: int, timeout: float) -> bool:
        self._set([(DTV_CLEAR, 0)])
        self._set(atsc_props(freq))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            buf = bytearray(4)
            try:
                fcntl.ioctl(self.fe, FE_READ_STATUS, buf, True)
            except OSError:
                pass
            if struct.unpack("<I", buf)[0] & FE_HAS_LOCK:
                return True
            time.sleep(0.01)
        return False

    def start(self) -> None:
        fcntl.ioctl(self.demux, DMX_START)

    def stop(self) -> None:
        try:
            fcntl.ioctl(self.demux, DMX_STOP)
        except OSError:
            pass

    def read(self) -> bytes:
        try:
            return os.read(self.dvr, READ_BYTES)
        except BlockingIOError:
            return b""
        except OSError as exc:
            # The ring overflowed while nothing read it. The next read is fresh.
            if exc.errno == errno.EOVERFLOW:
                return b""
            raise

    def drain(self) -> None:
        while self.read():
            pass

    def fileno(self) -> int:
        return self.dvr

    def snr(self) -> Optional[int]:
        buf = bytearray(2)
        try:
            fcntl.ioctl(self.fe, FE_READ_SNR, buf, True)
        except OSError:
            return None
        return struct.unpack("<H", buf)[0]

    def close(self) -> None:
        for fd in (self.dvr, self.demux, self.fe):
            try:
                os.close(fd)
            except OSError:
                pass


class TowerDump:
    def __init__(self, tuner, dest: str, log_path: str):
        self.tuner = tuner
        self.out = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        os.fchmod(self.out, 0o600)
        os.ftruncate(self.out, 0)
        self.log_file = open(log_path, "a", encoding="utf-8")
        self.born = time.monotonic()
        self.running = True
        self.freq = 0

    def log(self, message: str) -> None:
        self.log_file.write(f"[{time.monotonic() - self.born:8.3f}] {message}\n")
        self.log_file.flush()

    def _lock(self, freq: int) -> bool:
        began = time.monotonic()
        self.log(f"Tuning to {freq} Hz")
        locked = self.tuner.tune(freq, LOCK_TIMEOUT_SEC)
        took = time.monotonic() - began
        self.log(f"Locked after {took:.2f} s" if locked else f"No lock after {took:.2f} s")
        if locked:
            self.freq = int(freq)
        return locked

    def start(self, freq: int) -> bool:
        if not self._lock(freq):
            return False
        self.tuner.start()
        return True

    def pump(self) -> int:
        data = self.tuner.read()
        if data:
            os.write(self.out, data)
        return len(data)

    def note_signal(self) -> None:
        raw = self.tuner.snr()
        if raw is not None:
            self.log(f"SNR: {raw}")

    def handle(self, command: list) -> dict:
        name = command[0] if command else ""
        if name == "quit":
            self.running = False
            return {"error": "success"}
        if name == "tune":
            try:
                freq = int(command[1])
            except (IndexError, TypeError, ValueError):
                return {"error": "invalid parameter"}
            self.tuner.stop()
            self.tuner.drain()
            os.ftruncate(self.out, 0)
            if not self._lock(freq):
                return {"error": "no lock"}
            self.tuner.drain()
            self.tuner.start()
            return {"error": "success", "data": {"mark": 0}}
        return {"error": "unknown command"}

    def _answer(self, conn: socket.socket) -> None:
        conn.settimeout(1.0)
        buf = b""
        try:
            while b"\n" not in buf:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk
            request = json.loads(buf.split(b"\n", 1)[0].decode("utf-8") or "{}")
            reply = self.handle(list(request.get("command") or []))
            conn.sendall((json.dumps(reply) + "\n").encode("utf-8"))
        except (OSError, ValueError, AttributeError):
            pass

    def serve(self, sock_path: str, tick: float = 0.4) -> None:
        if os.path.exists(sock_path):
            os.unlink(sock_path)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(sock_path)
        os.chmod(sock_path, 0o600)
        server.listen(4)
        next_signal = 0.0
        try:
            while self.running:
                watch = [server]
                if self.tuner.fileno() >= 0:
                    watch.append(self.tuner.fileno())
                try:
                    ready, _, _ = select.select(watch, [], [], tick)
                except InterruptedError:
                    continue
                if server in ready:
                    conn, _ = server.accept()
                    with conn:
                        self._answer(conn)
                while self.pump():
                    pass
                now = time.monotonic()
                if now >= next_signal:
                    next_signal = now + SIGNAL_EVERY_SEC
                    self.note_signal()
        finally:
            server.close()
            try:
                os.unlink(sock_path)
            except OSError:
                pass

    def close(self) -> None:
        self.tuner.close()
        try:
            os.close(self.out)
        except OSError:
            pass
        self.log_file.close()


def main(argv: List[str]) -> int:
    if len(argv) != 6:
        sys.stderr.write(__doc__ or "")
        return 2
    adapter, freq, dest, sock_path, log_path = int(argv[1]), int(argv[2]), argv[3], argv[4], argv[5]
    dump = TowerDump(Tuner(adapter), dest, log_path)

    def stop(_signum, _frame):
        dump.running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        if not dump.start(freq):
            return 3
        dump.serve(sock_path)
        return 0
    finally:
        dump.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
