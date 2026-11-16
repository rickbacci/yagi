"""Clipboard paste is capped and timed out, and the text never rides on argv."""

import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest

from engine.clipboard import read_clipboard_text

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join(PROJECT_ROOT, "bin", "yagi")


def _install_paste(folder, body):
    path = os.path.join(folder, "wl-paste")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)
    os.chmod(path, stat.S_IRWXU)
    return path


class TestClipboardText(unittest.TestCase):
    def test_read_stops_at_the_byte_cap(self):
        with tempfile.TemporaryDirectory() as folder:
            _install_paste(
                folder,
                "#!/bin/sh\npython3 -c 'import sys; sys.stdout.buffer.write(b\"x\" * 10000)'\n",
            )
            old = os.environ.get("PATH", "")
            os.environ["PATH"] = folder + os.pathsep + old
            try:
                text = read_clipboard_text(max_bytes=256, timeout=2)
            finally:
                os.environ["PATH"] = old
        self.assertEqual(text, "x" * 256)

    def test_a_stalled_owner_does_not_hold_the_read(self):
        with tempfile.TemporaryDirectory() as folder:
            _install_paste(folder, "#!/bin/sh\nsleep 30\n")
            old = os.environ.get("PATH", "")
            os.environ["PATH"] = folder + os.pathsep + old
            try:
                started = time.monotonic()
                text = read_clipboard_text(max_bytes=256, timeout=0.2)
                elapsed = time.monotonic() - started
            finally:
                os.environ["PATH"] = old
        self.assertEqual(text, "")
        self.assertLess(elapsed, 2.0)

    def test_a_streaming_paste_stops_the_whole_group(self):
        with tempfile.TemporaryDirectory() as folder:
            sleep_pid = os.path.join(folder, "sleep.pid")
            written = os.path.join(folder, "bytes")
            _install_paste(
                folder,
                "#!/bin/sh\n"
                "python3 -c 'import os,time; open(os.environ[\"YAGI_SLEEP_PID\"],\"w\").write(str(os.getpid())); time.sleep(60)' &\n"
                "i=0\n"
                "while [ ! -s \"$YAGI_SLEEP_PID\" ]; do\n"
                "  i=$((i+1))\n"
                "  if [ \"$i\" -gt 300 ]; then exit 1; fi\n"
                "  sleep 0.01\n"
                "done\n"
                "python3 -c 'import os,sys\n"
                "n=0\n"
                "path=os.environ[\"YAGI_BYTES\"]\n"
                "chunk=b\"z\"*4096\n"
                "while True:\n"
                "    sys.stdout.buffer.write(chunk)\n"
                "    sys.stdout.buffer.flush()\n"
                "    n += len(chunk)\n"
                "    open(path,\"w\").write(str(n))\n"
                "'\n",
            )
            old = os.environ.get("PATH", "")
            os.environ["PATH"] = folder + os.pathsep + old
            os.environ["YAGI_SLEEP_PID"] = sleep_pid
            os.environ["YAGI_BYTES"] = written
            try:
                started = time.monotonic()
                text = read_clipboard_text(max_bytes=256, timeout=2)
                elapsed = time.monotonic() - started
                self.assertEqual(text, "z" * 256)
                self.assertLess(elapsed, 2.0)
                with open(sleep_pid, encoding="utf-8") as handle:
                    pid = int(handle.read().strip())
                deadline = time.monotonic() + 1.0
                while time.monotonic() < deadline:
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        break
                    time.sleep(0.05)
                else:
                    os.kill(pid, 9)
                    self.fail("the paste command's descendant was still running")
                if os.path.isfile(written):
                    with open(written, encoding="utf-8") as handle:
                        count = int(handle.read().strip() or "0")
                    self.assertLess(count, 2_000_000)
            finally:
                os.environ["PATH"] = old
                os.environ.pop("YAGI_SLEEP_PID", None)
                os.environ.pop("YAGI_BYTES", None)
                if os.path.isfile(sleep_pid):
                    try:
                        with open(sleep_pid, encoding="utf-8") as handle:
                            leftover = int(handle.read().strip())
                        os.kill(leftover, 9)
                    except (OSError, ValueError):
                        pass

    def test_cli_argv_is_only_the_command(self):
        with tempfile.TemporaryDirectory() as folder:
            seen = os.path.join(folder, "argv")
            _install_paste(
                folder,
                "#!/bin/sh\nprintf '%s\\n' \"$0\" \"$@\" > " + repr(seen) + "\nprintf 'News at 6'\n",
            )
            env = os.environ.copy()
            env["PATH"] = folder + os.pathsep + env.get("PATH", "")
            res = subprocess.run(
                [sys.executable, CLI, "clipboard-text"],
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertEqual(res.stdout, "News at 6")
            self.assertEqual(res.args[-1], "clipboard-text")
            with open(seen, encoding="utf-8") as handle:
                lines = [line.strip() for line in handle.readlines() if line.strip()]
        self.assertEqual(lines[-3:], ["--no-newline", "-t", "text/plain"])
        self.assertNotIn("News", " ".join(lines))


if __name__ == "__main__":
    unittest.main()
