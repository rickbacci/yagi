"""The record timer runs the last commit, not whatever is half-saved in the repo."""

import os
import subprocess
import tempfile
import time
import unittest

from engine.release import KEEP_NEWEST, KEEP_SECS, TIMER, UNITS, current_sha, install, publish, refresh, uninstall

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
}


class TestRelease(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = os.path.join(self.tmp.name, "repo")
        self.root = os.path.join(self.tmp.name, "share")
        os.makedirs(os.path.join(self.repo, "bin"))
        self._git("init", "-q")

    def tearDown(self):
        self.tmp.cleanup()

    def _git(self, *args):
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(GIT_ENV)
        subprocess.run(["git", "-C", self.repo, *args], check=True, capture_output=True, env=env)

    def _commit(self, text):
        path = os.path.join(self.repo, "bin", "yagi")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(path, 0o755)
        self._git("add", "-A")
        self._git("commit", "-q", "-m", text)

    def _current(self):
        with open(os.path.join(self.root, "current", "bin", "yagi"), encoding="utf-8") as f:
            return f.read()

    def test_uncommitted_edits_never_reach_the_timer(self):
        self._commit("one")
        with open(os.path.join(self.repo, "bin", "yagi"), "w", encoding="utf-8") as f:
            f.write("half saved")
        sha = publish(self.repo, self.root)
        self.assertEqual(self._current(), "one")
        self.assertEqual(current_sha(self.root), sha)
        self.assertTrue(os.access(os.path.join(self.root, "current", "bin", "yagi"), os.X_OK))

    def test_a_new_commit_moves_current_and_keeps_the_last_copy(self):
        self._commit("one")
        first = publish(self.repo, self.root)
        self._commit("two")
        second = publish(self.repo, self.root)
        self.assertEqual(self._current(), "two")
        self.assertTrue(os.path.isdir(os.path.join(self.root, "releases", first)))
        self.assertNotEqual(first, second)

    def test_old_copies_go_after_a_day(self):
        shas = []
        for i in range(KEEP_NEWEST + 3):
            self._commit(f"v{i}")
            shas.append(publish(self.repo, self.root))
        old = time.time() - KEEP_SECS - 60
        for i, sha in enumerate(shas[:-1]):
            os.utime(os.path.join(self.root, "releases", sha), (old - i, old - i))
        self._commit("last")
        last = publish(self.repo, self.root)
        left = set(os.listdir(os.path.join(self.root, "releases")))
        self.assertIn(last, left)
        self.assertIn(shas[-1], left)
        self.assertEqual(len(left), KEEP_NEWEST)

    def test_a_plugin_update_reaches_the_timer_on_its_next_tick(self):
        self.assertIsNone(refresh(self.root))
        self._commit("one")
        publish(self.repo, self.root)
        self.assertIsNone(refresh(self.root))
        self._commit("two")
        moved = refresh(self.root)
        self.assertEqual(moved, current_sha(self.root))
        self.assertEqual(self._current(), "two")

    def test_install_starts_the_timer_and_uninstall_leaves_nothing(self):
        os.makedirs(os.path.join(self.repo, "systemd", "user"))
        for name in UNITS:
            with open(os.path.join(self.repo, "systemd", "user", name), "w", encoding="utf-8") as f:
                f.write(name)
        self._commit("one")
        units = os.path.join(self.tmp.name, "units")
        calls = []
        sha = install(self.repo, self.root, units=units, run=lambda cmd, check: calls.append(cmd))
        self.assertEqual(current_sha(self.root), sha)
        self.assertEqual(sorted(os.listdir(units)), sorted(UNITS))
        self.assertIn(["systemctl", "--user", "enable", "--now", TIMER], calls)
        uninstall(self.root, units=units, run=lambda cmd, check: calls.append(cmd))
        self.assertEqual(os.listdir(units), [])
        self.assertFalse(os.path.exists(self.root))
        self.assertIn(["systemctl", "--user", "disable", "--now", TIMER], calls)


if __name__ == "__main__":
    unittest.main()
