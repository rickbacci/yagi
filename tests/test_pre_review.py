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


class TestQmllintFlags(unittest.TestCase):
    def test_a_longer_option_is_not_the_short_one(self):
        check = _load_check()
        longer = "\n".join([
            "  --property-override <name>",
            "  --type-info <file>",
            "  --alias-cycle",
            "  --signal-handler",
        ])
        self.assertEqual(check.qmllint_level_flags(longer), [])
        exact = "\n".join(f"  --{flag} <level>" for flag in ("property", "type", "alias", "signal"))
        self.assertEqual(
            check.qmllint_level_flags(exact),
            ["property", "type", "alias", "signal"],
        )
        both = "--property-override <name>\n--property <level>\n"
        self.assertEqual(check.qmllint_level_flags(both), ["property"])
        self.assertEqual(check.qmllint_level_flags(""), [])


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
        for title in (
            "Parsers stop at the end of the buffer, and repeated sections do not pile up.",
            "Captured command output is size-capped, and a timeout kills the process group.",
            "The release snapshot stays on the allowlist, and automatic setup does not use privilege.",
            "Clipboard paste is capped at 256 bytes, which holds a full guide search.",
            "Git names the checkout it reads, and the read is size-capped.",
            "A captured command never signals the caller's own process group.",
            "A machine with no tuner is not told that both tuners are busy.",
            "A missing mpv does not crash the player.",
            "The release copy and the record timer follow XDG_DATA_HOME.",
            "Agent and dev files stay out of the plugin copy.",
            "Omarchy plugin validate accepts this plugin.",
            "qmllint accepts the plugin QML.",
            "ruff accepts the Python.",
        ):
            self.assertIn(f"PASS  {title}", res.stdout)

    def test_the_blocked_commit_fails_each_finding(self):
        parent = tempfile.mkdtemp(prefix="pre-review-")
        path = os.path.join(parent, "old")
        # The checkout under test is the only directory git has to trust.
        # A worktree we create is owned by us, so it does not need its own entry.
        git = ["git", "-c", f"safe.directory={ROOT}", "-C", ROOT]
        try:
            have = subprocess.run(
                git + ["cat-file", "-t", BLOCKED],
                capture_output=True, text=True, timeout=30,
            )
            if have.returncode != 0:
                fetched = subprocess.run(
                    git + ["fetch", "--depth=1", "origin", BLOCKED],
                    capture_output=True, text=True, timeout=120,
                )
                self.assertEqual(fetched.returncode, 0, fetched.stderr)
            added = subprocess.run(
                git + ["worktree", "add", "--detach", path, BLOCKED],
                capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(added.returncode, 0, added.stderr)
            res = subprocess.run(
                [sys.executable, CHECK, path],
                capture_output=True, text=True, timeout=180,
            )
        finally:
            subprocess.run(
                git + ["worktree", "remove", "--force", path],
                capture_output=True, timeout=60,
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
