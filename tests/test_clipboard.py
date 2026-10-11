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
