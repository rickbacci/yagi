"""The record timer runs the last commit, not whatever is half-saved in the repo."""

import os
import subprocess
import tempfile
import time
import unittest
from unittest import mock

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

    def test_agent_and_dev_files_stay_out_of_the_snapshot(self):
        os.makedirs(os.path.join(self.repo, ".cursor"))
        os.makedirs(os.path.join(self.repo, "scripts"))
        os.makedirs(os.path.join(self.repo, "engine"))
        for path, text in (
            ("AGENTS.md", "agent\n"),
            (os.path.join(".cursor", "environment.json"), "{}\n"),
            (os.path.join("scripts", "dev-setup.sh"), "#!/bin/sh\n"),
            (".env", "TOKEN=1\n"),
            (os.path.join("engine", ".env"), "TOKEN=1\n"),
        ):
            with open(os.path.join(self.repo, path), "w", encoding="utf-8") as handle:
                handle.write(text)
        self._commit("one")
        publish(self.repo, self.root)
        current = os.path.join(self.root, "current")
        self.assertEqual(self._current(), "one")
        self.assertFalse(os.path.exists(os.path.join(current, "AGENTS.md")))
        self.assertFalse(os.path.exists(os.path.join(current, ".cursor")))
        self.assertFalse(os.path.exists(os.path.join(current, "scripts")))
        self.assertFalse(os.path.exists(os.path.join(current, ".env")))
        self.assertFalse(os.path.exists(os.path.join(current, "engine", ".env")))

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

    def test_data_home_is_the_release_root(self):
        from engine.release import default_root

        with mock.patch.dict(os.environ, {"XDG_DATA_HOME": self.tmp.name}):
            self.assertEqual(default_root(), os.path.join(self.tmp.name, "yagi"))

    def test_without_data_home_the_release_root_is_local_share(self):
        from engine.release import default_root

        env = {key: value for key, value in os.environ.items() if key != "XDG_DATA_HOME"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(default_root(), os.path.expanduser("~/.local/share/yagi"))

    def test_the_timer_unit_follows_data_home(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "systemd", "user", "yagi-record.service"), encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("${XDG_DATA_HOME:-$HOME/.local/share}/yagi/current/bin/yagi", text)

    def test_git_names_this_checkout(self):
        from engine import release

        seen = {}

        def fake(argv, **_kw):
            seen["argv"] = list(argv)
            return subprocess.CompletedProcess(argv, 0, b"abc\n", b"")

        with mock.patch.object(release, "capture", side_effect=fake):
            self.assertEqual(release._git(self.repo, "rev-parse", "HEAD"), b"abc\n")
        self.assertIn(f"safe.directory={os.path.abspath(self.repo)}", seen["argv"])
        self.assertNotIn("safe.directory=*", seen["argv"])


class TestReleaseTag(unittest.TestCase):
    def test_the_tag_checker_uses_manifest_and_does_not_publish(self):
        import subprocess
        import sys

        script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "check-release-tag.py")
        good = subprocess.run([sys.executable, script, "v0.1.7"], capture_output=True, text=True, timeout=30)
        bad = subprocess.run([sys.executable, script, "v9.9.9"], capture_output=True, text=True, timeout=30)
        notes = subprocess.run([sys.executable, script, "--notes"], capture_output=True, text=True, timeout=30)
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
        self.assertIn("v0.1.7 matches manifest.json", good.stdout)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("does not match manifest.json", bad.stdout)
        self.assertEqual(notes.returncode, 0, notes.stderr)
        self.assertIn("yagi install", notes.stdout.lower())


if __name__ == "__main__":
    unittest.main()
