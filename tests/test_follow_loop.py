"""The fifo reader loop, in this process. A broken pipe must not replace the fifo."""

import os
import signal
import socket
import stat
import sys
import tempfile
import threading
import time
import unittest

from engine.follow_ts import TsFollower

PACKET = b"\x47" + b"\x00" * 187


class TestFollowLoop(unittest.TestCase):
    def test_commands_move_the_cursor_and_a_broken_pipe_keeps_the_fifo(self):
        previous = signal.signal(signal.SIGPIPE, signal.SIG_IGN)
        try:
            self._run_loop()
        finally:
            signal.signal(signal.SIGPIPE, previous)

    def _run_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            live = os.path.join(tmp, "live.ts")
            sock = os.path.join(tmp, "follow.sock")
            fifo = os.path.join(tmp, "follow.fifo")
            with open(live, "wb") as handle:
                handle.write(PACKET * 80)
            os.mkfifo(fifo, 0o600)
            follower = TsFollower(live, 0, sock, fifo)
            trace = sys.gettrace()

            def target():
                if trace is not None:
                    sys.settrace(trace)
                follower.run()

            thread = threading.Thread(target=target, daemon=True)
            thread.start()
            deadline = time.time() + 2
            while time.time() < deadline and not os.path.exists(sock):
                time.sleep(0.02)
            reader = os.open(fifo, os.O_RDONLY)
            try:
                got = os.read(reader, 188)
                self.assertEqual(got[:1], b"\x47")
                self.assertEqual(self._cmd(sock, "POS"), str(follower.pos))
                self._cmd(sock, "PAUSE")
                deadline = time.time() + 1
                while time.time() < deadline and not follower._paused:
                    time.sleep(0.02)
                self.assertTrue(follower._paused)
                self._cmd(sock, "PACE 200000")
                self._cmd(sock, "PACE nope")
                self._cmd(sock, "CATCHUP")
                self._cmd(sock, "SEEK 1880")
                deadline = time.time() + 1
                while time.time() < deadline and follower.pos != 1880:
                    time.sleep(0.02)
                self.assertEqual(follower.pos, 1880)
                self._cmd(sock, "SEEK")
                self._cmd(sock, "NOPE")
                self._cmd(sock, "PLAY")
                os.close(reader)
                reader = -1
                deadline = time.time() + 2
                while time.time() < deadline and follower._out_fd is not None:
                    time.sleep(0.02)
                self.assertIsNone(follower._out_fd)
                self.assertTrue(stat.S_ISFIFO(os.stat(fifo).st_mode))
            finally:
                follower._running = False
                if reader >= 0:
                    os.close(reader)
                nudge = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
                os.close(nudge)
                thread.join(timeout=2)

    def _cmd(self, sock, line):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(1)
            client.connect(sock)
            client.sendall((line + "\n").encode())
            if line == "POS":
                return client.recv(64).decode().strip()
        return ""


if __name__ == "__main__":
    unittest.main()
