"""
Copy the live tower dump into a recording, from a byte on, until stopped.

A recording of the tower live TV already holds takes no second tuner. This
reads the dump through the file it opened, so the copy keeps going when live
TV moves to another tower and the dump is renamed out of its way. A file that
shrinks has started another tower underneath; the copy ends there. So does one
that stops growing, because its dump is gone.

Usage: live_copy.py SOURCE DEST START_BYTE
"""

from __future__ import annotations

import os
import signal
import sys
import time
from typing import Callable, List

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from engine.follow_ts import TS_PACKET, align_ts_offset, next_video_keyframe

CHUNK = TS_PACKET * 4096
IDLE_SECS = 60.0


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view):]


def copy(
    source: str,
    dest: str,
    start: int,
    running: Callable[[], bool] = lambda: True,
    idle: float = IDLE_SECS,
    nap: float = 0.2,
) -> int:
    """Copy until running() is false, the source shrinks, or it idles. Returns the last byte read."""
    src = os.open(source, os.O_RDONLY)
    out = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        size = os.fstat(src).st_size
        pos = align_ts_offset(min(max(0, int(start)), size))
        if size > pos:
            window = os.pread(src, min(4 * 1024 * 1024, size - pos), pos)
            pos += next_video_keyframe(window, 0)
        quiet_since = time.monotonic()
        while running():
            size = os.fstat(src).st_size
            if size < pos:
                break
            ready = align_ts_offset(size - pos)
            if ready >= TS_PACKET:
                data = os.pread(src, min(CHUNK, ready), pos)
                if data:
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
    if len(argv) != 4:
        sys.stderr.write(__doc__ or "")
        return 2
    stopped = []

    def stop(_signum, _frame):
        stopped.append(True)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    copy(argv[1], argv[2], int(argv[3]), running=lambda: not stopped)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
