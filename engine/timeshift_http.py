"""127.0.0.1 HTTP view of live.ts: start at a playhead, wait at EOF.

mpv plays this URL. Skip is a new GET from a new byte, same window — not a pipe,
not pip-relaunch. Bind loopback only.
"""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

from engine.paths import TIMESHIFT_FILE

TS_PACKET = 188
CHUNK = TS_PACKET * 64


def align_ts(n: int) -> int:
    n = max(0, int(n or 0))
    return n - (n % TS_PACKET)


def _file_size() -> int:
    try:
        return int(os.path.getsize(TIMESHIFT_FILE))
    except OSError:
        return 0


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        return

    def do_HEAD(self) -> None:
        self._begin(body=False)

    def do_GET(self) -> None:
        self._begin(body=True)

    def _start_byte(self) -> int:
        query = parse_qs(urlparse(self.path).query)
        raw = (query.get("from") or [None])[0]
        if raw is not None:
            try:
                return align_ts(int(raw))
            except ValueError:
                pass
        rng = self.headers.get("Range") or ""
        if rng.lower().startswith("bytes="):
            spec = rng.split("=", 1)[1].split("-", 1)[0].strip()
            try:
                return align_ts(int(spec))
            except ValueError:
                pass
        size = _file_size()
        return align_ts(max(0, size - 188))

    def _begin(self, body: bool) -> None:
        start = self._start_byte()
        self.send_response(206)
        self.send_header("Content-Type", "video/mp2t")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        if not body:
            return
        try:
            self._stream(start)
        except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
            return

    def _write_chunk(self, data: bytes) -> None:
        if not data:
            return
        self.wfile.write(f"{len(data):X}\r\n".encode("ascii") + data + b"\r\n")
        self.wfile.flush()

    def _stream(self, pos: int) -> None:
        fd: Optional[int] = None
        inode = 0
        try:
            while not getattr(self.server, "shutting_down", False):
                try:
                    st = os.stat(TIMESHIFT_FILE)
                except FileNotFoundError:
                    time.sleep(0.05)
                    continue
                if fd is None or st.st_ino != inode or st.st_size < pos:
                    if fd is not None:
                        try:
                            os.close(fd)
                        except OSError:
                            pass
                    fd = os.open(TIMESHIFT_FILE, os.O_RDONLY)
                    inode = st.st_ino
                    pos = min(pos, align_ts(st.st_size))
                    os.lseek(fd, pos, os.SEEK_SET)
                buf = os.read(fd, CHUNK)
                if buf:
                    pos += len(buf)
                    self._write_chunk(buf)
                    continue
                time.sleep(0.04)
        finally:
            try:
                self.wfile.write(b"0\r\n\r\n")
            except OSError:
                pass
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass


class TimeshiftHttp:
    def __init__(self) -> None:
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self.port = 0

    def start(self) -> int:
        self.stop()
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        httpd.shutting_down = False  # type: ignore[attr-defined]
        self._httpd = httpd
        self.port = int(httpd.server_address[1])
        t = threading.Thread(target=httpd.serve_forever, name="tv-timeshift-http", daemon=True)
        t.start()
        self._thread = t
        return self.port

    def stop(self) -> None:
        httpd = self._httpd
        self._httpd = None
        if httpd is not None:
            httpd.shutting_down = True  # type: ignore[attr-defined]
            httpd.shutdown()
            httpd.server_close()
        t = self._thread
        self._thread = None
        if t is not None:
            t.join(timeout=1.0)
        self.port = 0


def main(argv: Optional[list] = None) -> None:
    """Sidecar: print the bound port, then serve until SIGTERM. Outlives `omarchy-tv play`."""
    global TIMESHIFT_FILE
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        TIMESHIFT_FILE = args[0]
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.shutting_down = False  # type: ignore[attr-defined]
    port = int(httpd.server_address[1])

    def _stop(*_a) -> None:
        httpd.shutting_down = True  # type: ignore[attr-defined]
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    def _watch_pause_cap() -> None:
        from engine.timeshift import Timeshift
        while not getattr(httpd, "shutting_down", False):
            try:
                Timeshift.hold_dump_if_full()
            except Exception:
                pass
            time.sleep(2.0)

    threading.Thread(target=_watch_pause_cap, name="tv-pause-cap", daemon=True).start()
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    sys.stdout.write(f"{port}\n")
    sys.stdout.flush()
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
