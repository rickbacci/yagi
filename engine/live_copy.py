"""
Copy one channel out of the live tower dump into a recording, until stopped.

A recording of the tower live TV already holds takes no second tuner. This
reads the dump through the file it opened, so the copy keeps going when live
TV moves to another tower and the dump is renamed out of its way. A file that
shrinks has started another tower underneath; the copy ends there. So does one
that stops growing, because its dump is gone.

Only the channel's packets are kept: the PAT, its PMT, and the streams that
PMT lists. The file opens with the tables, then a keyframe of its video. A
channel whose PMT does not show up in time is copied as the whole tower.

Usage: live_copy.py SOURCE DEST START_BYTE [SERVICE_ID]
"""

from __future__ import annotations

import os
import signal
import sys
import time
from typing import Callable, Dict, List, Optional, Set

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from engine.follow_ts import TS_PACKET, align_ts_offset, next_video_keyframe, packet_is_video_keyframe, packet_pid
from engine.psip import _VIDEO_TYPES

CHUNK = TS_PACKET * 4096
IDLE_SECS = 60.0
# PAT comes every 100 ms and a PMT every 400 ms; this is several seconds of a whole tower.
LEARN_BYTES = 16 * 1024 * 1024
PAT_PID = 0
NULL_PID = 0x1FFF


class ProgramFilter:
    """The packets of one program: the PAT, its PMT, and every stream that PMT lists."""

    def __init__(self, service_id: int):
        self.service_id = int(service_id)
        self.pmt_pid: Optional[int] = None
        self.streams: Set[int] = set()
        self.video = 0
        self.tables: Dict[int, bytes] = {}
        self._partial: Dict[int, bytearray] = {}

    @property
    def ready(self) -> bool:
        return self.pmt_pid is not None and bool(self.streams)

    def keeps(self, pid: int) -> bool:
        return pid == PAT_PID or pid == self.pmt_pid or pid in self.streams

    def learn(self, pkt: bytes) -> None:
        pid = packet_pid(pkt)
        if pid != PAT_PID and pid != self.pmt_pid:
            return
        section = self._section(pid, pkt)
        if section is None:
            return
        if pid == PAT_PID:
            self._pat(section)
        else:
            self._pmt(section)
        if pkt[1] & 0x40:
            self.tables[pid] = bytes(pkt)

    def _section(self, pid: int, pkt: bytes) -> Optional[bytes]:
        afc = (pkt[3] >> 4) & 0x3
        if afc in (0, 2):
            return None
        off = 4 + (1 + pkt[4] if afc == 3 else 0)
        if off >= TS_PACKET:
            return None
        payload = pkt[off:]
        if pkt[1] & 0x40:
            buf = bytearray(payload[1 + payload[0]:])
        elif pid in self._partial:
            buf = self._partial[pid] + payload
        else:
            return None
        total = 3 + (((buf[1] & 0x0F) << 8) | buf[2]) if len(buf) >= 3 else TS_PACKET * 8
        if len(buf) < total:
            self._partial[pid] = buf
            return None
        self._partial.pop(pid, None)
        return bytes(buf[:total])

    def _pat(self, s: bytes) -> None:
        if s[0] != 0x00:
            return
        for i in range(8, len(s) - 4 - 3, 4):
            if ((s[i] << 8) | s[i + 1]) == self.service_id:
                pid = ((s[i + 2] & 0x1F) << 8) | s[i + 3]
                if pid != self.pmt_pid:
                    self.pmt_pid, self.streams, self.video = pid, set(), 0
                return

    def _pmt(self, s: bytes) -> None:
        if s[0] != 0x02 or len(s) < 16 or ((s[3] << 8) | s[4]) != self.service_id:
            return
        streams = {((s[8] & 0x1F) << 8) | s[9]}
        video = 0
        i = 12 + (((s[10] & 0x0F) << 8) | s[11])
        end = len(s) - 4
        while i + 5 <= end:
            pid = ((s[i + 1] & 0x1F) << 8) | s[i + 2]
            streams.add(pid)
            if s[i] in _VIDEO_TYPES and not video:
                video = pid
            i += 5 + (((s[i + 3] & 0x0F) << 8) | s[i + 4])
        streams.discard(NULL_PID)
        self.streams, self.video = streams, video


def _packets(data: bytes):
    for off in range(0, len(data) - TS_PACKET + 1, TS_PACKET):
        pkt = data[off:off + TS_PACKET]
        if pkt[0] == 0x47:
            yield off, pkt


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view):]


def _learn(src: int, pos: int, filt: ProgramFilter, running: Callable[[], bool],
           idle: float, nap: float, limit: int) -> Optional[int]:
    """Read ahead until the program's tables are known. Returns its first video keyframe at or after pos.

    A GOP can be a couple of megabytes of tower past the tables, and at the
    live edge it may not be written yet.
    """
    def scan_from(at: int, done: Callable[[int, bytes], Optional[int]]) -> Optional[int]:
        quiet_since = time.monotonic()
        while running() and at - pos < limit:
            ready = align_ts_offset(os.fstat(src).st_size - at)
            if ready < TS_PACKET:
                if time.monotonic() - quiet_since >= idle:
                    return None
                time.sleep(nap)
                continue
            data = os.pread(src, min(CHUNK, ready), at)
            hit = done(at, data)
            if hit is not None:
                return hit
            at += len(data)
            quiet_since = time.monotonic()
        return None

    def tables(at: int, data: bytes) -> Optional[int]:
        for _, pkt in _packets(data):
            filt.learn(pkt)
        return at if filt.ready else None

    def keyframe(at: int, data: bytes) -> Optional[int]:
        for off, pkt in _packets(data):
            if packet_pid(pkt) == filt.video and packet_is_video_keyframe(pkt):
                return at + off
        return None

    if scan_from(pos, tables) is None:
        return None
    found = scan_from(pos, keyframe) if filt.video else None
    return pos if found is None else found


def copy(
    source: str,
    dest: str,
    start: int,
    service_id: int = 0,
    running: Callable[[], bool] = lambda: True,
    idle: float = IDLE_SECS,
    nap: float = 0.2,
    learn_bytes: int = LEARN_BYTES,
) -> int:
    """Copy until running() is false, the source shrinks, or it idles. Returns the last byte read."""
    src = os.open(source, os.O_RDONLY)
    out = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        size = os.fstat(src).st_size
        pos = align_ts_offset(min(max(0, int(start)), size))
        filt: Optional[ProgramFilter] = ProgramFilter(service_id) if service_id > 0 else None
        found = _learn(src, pos, filt, running, idle, nap, learn_bytes) if filt else None
        if found is None:
            filt = None
            size = os.fstat(src).st_size
            if size > pos:
                window = os.pread(src, min(4 * 1024 * 1024, size - pos), pos)
                pos += next_video_keyframe(window, 0)
        else:
            pos = found
            _write_all(out, b"".join(filt.tables[pid] for pid in (PAT_PID, filt.pmt_pid) if pid in filt.tables))
        quiet_since = time.monotonic()
        while running():
            size = os.fstat(src).st_size
            if size < pos:
                break
            ready = align_ts_offset(size - pos)
            if ready >= TS_PACKET:
                data = os.pread(src, min(CHUNK, ready), pos)
                if data:
                    if filt is not None:
                        kept = []
                        for _, pkt in _packets(data):
                            filt.learn(pkt)
                            if filt.keeps(packet_pid(pkt)):
                                kept.append(pkt)
                        _write_all(out, b"".join(kept))
                    else:
                        _write_all(out, data)
                    pos += len(data)
                    quiet_since = time.monotonic()
                    continue
            if time.monotonic() - quiet_since >= idle:
                break
            time.sleep(nap)
        return pos
    finally:
        os.close(src)
        os.close(out)


def main(argv: List[str]) -> int:
    if len(argv) not in (4, 5):
        sys.stderr.write(__doc__ or "")
        return 2
    stopped = []

    def stop(_signum, _frame):
        stopped.append(True)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    os.nice(10)
    service = int(argv[4]) if len(argv) == 5 else 0
    copy(argv[1], argv[2], int(argv[3]), service_id=service, running=lambda: not stopped)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
