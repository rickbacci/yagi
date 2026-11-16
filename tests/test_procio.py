"""A captured child must not be able to signal the caller's process group."""

import os
import subprocess
import unittest
from unittest import mock

from engine.procio import _kill_group, capture


class TestProcessGroup(unittest.TestCase):
    def test_a_child_that_stayed_in_our_group_is_not_killpgd(self):
        child = subprocess.Popen(["sleep", "30"])
        sibling = subprocess.Popen(["sleep", "30"])
        try:
            self.assertEqual(os.getpgid(child.pid), os.getpgrp())
            with mock.patch("engine.procio.os.killpg") as killpg:
                _kill_group(child)
            killpg.assert_not_called()
            sibling.wait(timeout=0.2)
        except subprocess.TimeoutExpired:
            pass
        else:
            self.fail("a sibling in our group died with the child")
        finally:
            for proc in (child, sibling):
                try:
                    proc.kill()
                    proc.wait(timeout=2)
                except OSError:
                    pass

    def test_a_new_session_is_killed_and_our_group_is_not(self):
        sibling = subprocess.Popen(["sleep", "30"])
        try:
            with self.assertRaises(subprocess.TimeoutExpired):
                capture(
                    ["python3", "-c", "import time; time.sleep(30)"],
                    max_bytes=8,
                    timeout=0.4,
                )
            os.kill(sibling.pid, 0)
        finally:
            try:
                sibling.kill()
                sibling.wait(timeout=2)
            except OSError:
                pass

    def test_a_descendant_in_the_new_session_dies(self):
        sleep_pid = None
        script = (
            "set +m\n"
            "python3 -c 'import os,time; open(os.environ[\"P\"],\"w\").write(str(os.getpid())); time.sleep(30)' &\n"
            "i=0\n"
            "while [ ! -s \"$P\" ]; do i=$((i+1)); [ \"$i\" -gt 200 ] && exit 1; sleep 0.01; done\n"
            "python3 -c 'import sys,time; sys.stdout.buffer.write(b\"z\"*64); sys.stdout.buffer.flush(); time.sleep(30)'\n"
        )
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "pid")
            env = dict(os.environ)
            env["P"] = path
            capture(["sh", "-c", script], max_bytes=32, timeout=2, env=env)
            with open(path, encoding="utf-8") as handle:
                sleep_pid = int(handle.read().strip())
        deadline_alive = True
        try:
            os.kill(sleep_pid, 0)
        except ProcessLookupError:
            deadline_alive = False
        self.assertFalse(deadline_alive)


if __name__ == "__main__":
    unittest.main()
