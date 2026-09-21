"""
Copy a growing MPEG-TS file to stdout and wait at EOF instead of closing.

Windowed MPV reads this pipe. lavf on a file hits EOF at the size it opened;
a pipe blocks until more bytes arrive, so the picture keeps moving. SEEK <byte>
on the control socket jumps the read cursor (skip / return-to-live).
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


def align_ts_offset(n: int) -> int:
    n = int(n or 0)
    if n <= 0:
        return 0
    return n - (n % TS_PACKET)


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

    def _apply_seek(self, byte: int) -> None:
        target = align_ts_offset(byte)
        with self._lock:
            self.pos = target
            if self._fd is None:
                return
            try:
                size = os.fstat(self._fd).st_size
                if self.pos > size:
                    self.pos = align_ts_offset(size)
                os.lseek(self._fd, self.pos, os.SEEK_SET)
            except OSError:
                pass

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
            if data.upper().startswith("PAUSE"):
                self._paused = True
                continue
            if data.upper().startswith("REOPEN"):
                self._paused = False
                self._reopen_from_start()
                continue
            if data.upper().startswith("SEEK"):
                parts = data.split()
                try:
                    self._apply_seek(int(parts[1]))
                except (IndexError, ValueError):
                    pass

    def run(self) -> None:
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
        self._bind_sock()
        self._open_file()
        self._open_dest()
        ctl = threading.Thread(target=self._ctl_loop, name="follow-ctl", daemon=True)
        ctl.start()
        stdout = sys.stdout.buffer
        try:
            while self._running:
                if self._paused:
                    time.sleep(0.04)
                    continue
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
                if buf:
                    try:
                        if self._out_fd is not None:
                            os.write(self._out_fd, buf)
                        else:
                            stdout.write(buf)
                            stdout.flush()
                    except (BrokenPipeError, OSError):
                        if not self.dest_fifo:
                            return
                        if self._out_fd is not None:
                            try:
                                os.close(self._out_fd)
                            except OSError:
                                pass
                            self._out_fd = None
                        self._open_dest()
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
