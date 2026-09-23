"""
Copy a growing MPEG-TS file to stdout and wait at EOF instead of closing.

Windowed MPV reads this pipe. lavf on a file hits EOF at the size it opened;
a pipe blocks until more bytes arrive, so the picture keeps moving. SEEK <byte>
on the control socket jumps the read cursor (skip / return-to-live). POS
replies with the current cursor so skip can move from the real playhead.
Unpaced copy dumps the rest of the file as fast as the pipe allows, so a
delayed skip never moves the picture. PACE <bytes/sec> reads the buffer at
1x. CATCHUP turns that off and races to the write head.

SEEK lands on the next video keyframe at or after the byte, then keeps
writing the same fifo. The window stays open. A cursor file beside the
control socket is the byte the behind number subtracts from the file end.
"""

from __future__ import annotations

import os
import signal
import socket
import sys
import threading
import time
from typing import List, Optional

TS_PACKET = 188
CHUNK = TS_PACKET * 64
PACE_LEAD_SEC = 3.0


def align_ts_offset(n: int) -> int:
    n = int(n or 0)
    if n <= 0:
        return 0
    return n - (n % TS_PACKET)


def cursor_path(sock_path: str) -> str:
    if sock_path.endswith(".sock"):
        return sock_path[:-5] + ".pos"
    return sock_path + ".pos"


def packet_is_video_keyframe(pkt: bytes) -> bool:
    """True when this TS packet begins a video random-access point.

    MPEG-2 sequence header, an I-picture, or an H.264 IDR. The packet has to
    start a payload unit so the cut is on a PES boundary.
    """
    if len(pkt) < TS_PACKET or pkt[0] != 0x47:
        return False
    if (pkt[1] & 0x40) == 0:
        return False
    afc = (pkt[3] >> 4) & 0x3
    off = 4
    if afc in (2, 3):
        afl = pkt[4]
        off = 5 + afl
        if off > TS_PACKET:
            return False
    if afc == 2:
        return False
    body = pkt[off:]
    if b"\x00\x00\x01\xb3" in body or b"\x00\x00\x01\x65" in body or b"\x00\x00\x00\x01\x65" in body:
        return True
    idx = body.find(b"\x00\x00\x01\x00")
    if idx < 0 or idx + 6 > len(body):
        return False
    coding = (body[idx + 5] >> 3) & 0x07
    return coding == 1


def packet_pid(pkt: bytes) -> int:
    if len(pkt) < 4 or pkt[0] != 0x47:
        return -1
    return ((pkt[1] & 0x1F) << 8) | pkt[2]


def discontinuity_packet(pid: int) -> bytes:
    """Adaptation-only packet. The next payload on this PID is a new timeline."""
    pkt = bytearray(TS_PACKET)
    pkt[0] = 0x47
    pkt[1] = (pid >> 8) & 0x1F
    pkt[2] = pid & 0xFF
    pkt[3] = 0x20
    pkt[4] = TS_PACKET - 5
    pkt[5] = 0x80
    for i in range(6, TS_PACKET):
        pkt[i] = 0xFF
    return bytes(pkt)


def mark_discontinuity(buf: bytes) -> bytes:
    """Prefix a break packet for each elementary stream in this chunk."""
    if not buf or buf[0] != 0x47:
        return buf
    seen = set()
    prefix = bytearray()
    for off in range(0, len(buf) - TS_PACKET + 1, TS_PACKET):
        if buf[off] != 0x47:
            break
        pid = packet_pid(buf[off:off + TS_PACKET])
        if pid < 0 or pid == 0x1FFF or pid in seen:
            continue
        seen.add(pid)
        prefix += discontinuity_packet(pid)
    return bytes(prefix) + buf


def next_video_keyframe(data: bytes, start: int) -> int:
    """Offset of the next video keyframe at or after start.

    Junk that is not MPEG-TS stays on the aligned byte. A real stream with
    no keyframe in the buffer stays there too, so a seek never waits forever.
    """
    start = align_ts_offset(start)
    if start < 0 or start >= len(data):
        return max(0, start)
    if data[start:start + 1] != b"\x47":
        return start
    limit = min(len(data), start + 4 * 1024 * 1024)
    pos = start
    while pos + TS_PACKET <= limit:
        if packet_is_video_keyframe(data[pos:pos + TS_PACKET]):
            return pos
        pos += TS_PACKET
    return start


class TsFollower:
    def __init__(self, path: str, start_byte: int, sock_path: str, dest_fifo: Optional[str] = None):
        self.path = path
        self.pos = align_ts_offset(start_byte)
        self.sock_path = sock_path
        self.dest_fifo = dest_fifo or ""
        self._fd: Optional[int] = None
        self._out_fd: Optional[int] = None
        self._srv: Optional[socket.socket] = None
        self._lock = threading.Lock()
        self._reopen_gate = threading.Lock()
        self._running = True
        self._paused = False
        self._paced = False
        self._pace_bps = 0.0
        self._pace_origin_t = 0.0
        self._pace_origin_pos = 0
        self._write_bps = 0.0
        self._eof_t: Optional[float] = None
        self._eof_size = 0
        self._pos_note_t = 0.0
        self._pos_path = cursor_path(sock_path)
        self._break = False

    def _open_dest(self) -> None:
        if not self.dest_fifo:
            return
        while self._running:
            try:
                self._out_fd = os.open(self.dest_fifo, os.O_WRONLY)
                return
            except FileNotFoundError:
                time.sleep(0.05)
            except OSError:
                time.sleep(0.05)

    def _open_file(self) -> None:
        while self._running:
            try:
                fd = os.open(self.path, os.O_RDONLY)
                size = os.fstat(fd).st_size
                with self._lock:
                    if self.pos > size:
                        self.pos = align_ts_offset(size)
                    os.lseek(fd, self.pos, os.SEEK_SET)
                    self._fd = fd
                return
            except FileNotFoundError:
                time.sleep(0.05)

    def _bind_sock(self) -> None:
        if os.path.exists(self.sock_path):
            try:
                os.unlink(self.sock_path)
            except OSError:
                pass
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(self.sock_path)
        srv.listen(4)
        srv.settimeout(0.2)
        self._srv = srv

    def _reopen_from_start(self) -> None:
        """Drop the current inode and wait for PATH to exist again (channel change)."""
        with self._reopen_gate:
            with self._lock:
                if self._fd is not None:
                    try:
                        os.close(self._fd)
                    except OSError:
                        pass
                    self._fd = None
                self.pos = 0
            self._open_file()

    def _maybe_reopen(self) -> None:
        """Follow a replaced or truncated live.ts instead of sitting on a dead inode."""
        with self._lock:
            fd = self._fd
            pos = self.pos
        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            self._reopen_from_start()
            return
        if fd is None:
            self._open_file()
            return
        try:
            fd_st = os.fstat(fd)
        except OSError:
            self._reopen_from_start()
            return
        if st.st_ino != fd_st.st_ino or st.st_size < pos:
            self._reopen_from_start()

    def _reset_pace_clock(self) -> None:
        self._pace_origin_t = time.monotonic()
        self._pace_origin_pos = self.pos

    def _pace_wait(self) -> None:
        """Block until the cursor is allowed. A capped nap lets a slow pace leak."""
        while self._running and self._paced and self._pace_bps > 0 and not self._paused:
            with self._lock:
                elapsed = time.monotonic() - self._pace_origin_t
                allowed = self._pace_origin_pos + elapsed * self._pace_bps
                lead = min(self._pace_bps * PACE_LEAD_SEC, 3 * 1024 * 1024)
                if self.pos <= allowed + lead:
                    return
                extra = (self.pos - allowed - lead) / self._pace_bps
            time.sleep(min(max(0.0, extra), 0.05))

    def _publish_pos(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - self._pos_note_t) < 0.25:
            return
        self._pos_note_t = now
        tmp = self._pos_path + ".tmp"
        try:
            fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        except OSError:
            return
        try:
            os.write(fd, str(self.pos).encode())
        except OSError:
            try:
                os.close(fd)
            except OSError:
                pass
            return
        try:
            os.close(fd)
            os.replace(tmp, self._pos_path)
        except OSError:
            pass

    def _apply_seek(self, byte: int) -> None:
        """Move the read cursor. The fifo stays open."""
        target = align_ts_offset(byte)
        with self._lock:
            fd = self._fd
            size = 0
            window = b""
            if fd is not None:
                try:
                    size = os.fstat(fd).st_size
                    if target < size:
                        os.lseek(fd, target, os.SEEK_SET)
                        window = os.read(fd, min(4 * 1024 * 1024, size - target))
                except OSError:
                    window = b""
            cut = target
            if window:
                cut = target + next_video_keyframe(window, 0)
            if size and cut > size:
                cut = align_ts_offset(size)
            self.pos = cut
            if fd is not None:
                try:
                    os.lseek(fd, self.pos, os.SEEK_SET)
                except OSError:
                    pass
            self._reset_pace_clock()
            self._break = True
        self._publish_pos(force=True)

    def _handle_ctl(self, data: str) -> Optional[str]:
        upper = data.upper()
        if upper.startswith("POS"):
            with self._lock:
                return str(self.pos)
        if upper.startswith("PAUSE"):
            self._paused = True
            self._publish_pos(force=True)
            return None
        if upper.startswith("PLAY"):
            self._paused = False
            self._reset_pace_clock()
            return None
        if upper.startswith("PACE"):
            parts = data.split()
            self._paced = True
            if len(parts) > 1:
                try:
                    bps = float(parts[1])
                    if bps > 0:
                        self._pace_bps = bps
                except ValueError:
                    pass
            if self._pace_bps <= 0 and self._write_bps > 0:
                self._pace_bps = self._write_bps
            self._reset_pace_clock()
            return None
        if upper.startswith("CATCHUP"):
            self._paced = False
            return None
        if upper.startswith("REOPEN"):
            self._paused = False
            self._paced = False
            self._reopen_from_start()
            return None
        if upper.startswith("SEEK"):
            parts = data.split()
            try:
                self._apply_seek(int(parts[1]))
            except (IndexError, ValueError):
                pass
            return None
        return None

    def _ctl_loop(self) -> None:
        while self._running and self._srv is not None:
            try:
                conn, _ = self._srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                conn.settimeout(0.3)
                try:
                    data = conn.recv(256).decode("utf-8", "replace").strip()
                except OSError:
                    continue
                if not data:
                    continue
                reply = self._handle_ctl(data)
                if reply is not None:
                    try:
                        conn.sendall(reply.encode())
                    except OSError:
                        pass

    def run(self) -> None:
        # A probe can open the fifo and close it. Default SIGPIPE would kill
        # the reader. Ignore it and wait for the real window.
        signal.signal(signal.SIGPIPE, signal.SIG_IGN)
        self._bind_sock()
        self._open_file()
        ctl = threading.Thread(target=self._ctl_loop, name="follow-ctl", daemon=True)
        ctl.start()
        self._open_dest()
        stdout = sys.stdout.buffer
        try:
            while self._running:
                if self._paused:
                    time.sleep(0.04)
                    continue
                stamp = False
                with self._lock:
                    fd = self._fd
                    if fd is None:
                        buf = b""
                    else:
                        try:
                            buf = os.read(fd, CHUNK)
                        except OSError:
                            buf = b""
                        if buf:
                            self.pos += len(buf)
                            stamp = self._break
                            self._break = False
                file_len = len(buf)
                if buf and stamp:
                    buf = mark_discontinuity(buf)
                if buf:
                    self._publish_pos()
                    try:
                        if self._out_fd is not None:
                            pending = buf
                            while pending:
                                wrote = os.write(self._out_fd, pending)
                                if wrote <= 0:
                                    raise BrokenPipeError
                                pending = pending[wrote:]
                        else:
                            stdout.write(buf)
                            stdout.flush()
                    except (BrokenPipeError, OSError):
                        with self._lock:
                            self.pos = max(0, self.pos - file_len)
                            if stamp:
                                self._break = True
                            if self._fd is not None:
                                try:
                                    os.lseek(self._fd, self.pos, os.SEEK_SET)
                                except OSError:
                                    pass
                        if not self.dest_fifo:
                            return
                        if self._out_fd is not None:
                            try:
                                os.close(self._out_fd)
                            except OSError:
                                pass
                            self._out_fd = None
                        self._open_dest()
                    self._pace_wait()
                else:
                    self._maybe_reopen()
                    time.sleep(0.04)
        finally:
            self._running = False
            if self._fd is not None:
                try:
                    os.close(self._fd)
                except OSError:
                    pass
                self._fd = None
            if self._out_fd is not None:
                try:
                    os.close(self._out_fd)
                except OSError:
                    pass
                self._out_fd = None
            if self._srv is not None:
                try:
                    self._srv.close()
                except OSError:
                    pass
            if os.path.exists(self.sock_path):
                try:
                    os.unlink(self.sock_path)
                except OSError:
                    pass


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 3:
        sys.stderr.write("usage: follow_ts.py PATH START_BYTE SOCK [FIFO]\n")
        return 2
    fifo = args[3] if len(args) > 3 else None
    TsFollower(args[0], int(args[1]), args[2], fifo).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
