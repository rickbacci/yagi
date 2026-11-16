"""The pre-review check passes on this tree and fails on the blocked 0.1.7 commit."""

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECK = os.path.join(ROOT, "scripts", "pre_review.py")
BLOCKED = "4b70b5b4361ea8bfa9576254beefc32da52bcd26"


def _load_check():
    spec = importlib.util.spec_from_file_location("pre_review", CHECK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestPreReview(unittest.TestCase):
    def test_the_allowlist_matches_the_snapshot(self):
        from engine.release import SNAPSHOT_DIRS, SNAPSHOT_FILES

        check = _load_check()
        self.assertEqual(check.ALLOW_DIRS, SNAPSHOT_DIRS)
        self.assertEqual(check.ALLOW_FILES, SNAPSHOT_FILES)

    def test_this_tree_passes(self):
        res = subprocess.run(
            [sys.executable, CHECK],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("Pre-review check passed.", res.stdout)

    def test_the_blocked_commit_fails_each_finding(self):
        parent = tempfile.mkdtemp(prefix="pre-review-")
        path = os.path.join(parent, "old")
        try:
            added = subprocess.run(
                ["git", "-c", "safe.directory=*", "-C", ROOT, "worktree", "add", "--detach", path, BLOCKED],
                capture_output=True, text=True,
            )
            self.assertEqual(added.returncode, 0, added.stderr)
            res = subprocess.run(
                [sys.executable, CHECK, path],
                capture_output=True, text=True,
            )
        finally:
            subprocess.run(
                ["git", "-c", "safe.directory=*", "-C", ROOT, "worktree", "remove", "--force", path],
                capture_output=True,
            )
            shutil.rmtree(parent, ignore_errors=True)
        self.assertNotEqual(res.returncode, 0, res.stdout)
        text = res.stdout + res.stderr
        self.assertIn("parse_eit", text)
        self.assertIn("BitReader", text)
        self.assertIn("engine/clipboard.py", text)
        self.assertIn("AGENTS.md", text)
        self.assertIn(".cursor/environment.json", text)
        self.assertIn("loginctl", text)
        self.assertIn("sudo", text)


if __name__ == "__main__":
    unittest.main()
