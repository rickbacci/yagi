"""The record timer runs a copy of the last commit, never the working tree.

Each commit unpacks to ~/.local/share/omarchy-tv/releases/<sha>, and current
points at it. An edit saved halfway in the repo never reaches a recording.
Standard library only: the git hooks run this without the app's environment.
"""

import io
import os
import shutil
import subprocess
import sys
import tarfile
import time
from typing import Optional

DEFAULT_ROOT = os.path.expanduser("~/.local/share/omarchy-tv")
# A record finish or Guide update can still be running from an older copy.
KEEP_NEWEST = 3
KEEP_SECS = 24 * 3600


def _git(repo: str, *args: str) -> bytes:
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True).stdout


def current_sha(root: str = DEFAULT_ROOT) -> str:
    try:
        return os.path.basename(os.readlink(os.path.join(root, "current")))
    except OSError:
        return ""


def _prune(releases: str, keep: set, now: float) -> None:
    dirs = sorted(
        (e for e in os.scandir(releases) if e.is_dir(follow_symlinks=False) and not e.name.startswith(".")),
        key=lambda e: e.stat().st_mtime,
        reverse=True,
    )
    for i, entry in enumerate(dirs):
        if entry.name in keep or i < KEEP_NEWEST or now - entry.stat().st_mtime < KEEP_SECS:
            continue
        shutil.rmtree(entry.path, ignore_errors=True)


def publish(repo: str, root: str = DEFAULT_ROOT, now: Optional[float] = None) -> str:
    """Unpack HEAD and point current at it. Returns the short sha."""
    sha = _git(repo, "rev-parse", "--short=12", "HEAD").decode().strip()
    releases = os.path.join(root, "releases")
    os.makedirs(releases, mode=0o700, exist_ok=True)
    dest = os.path.join(releases, sha)
    if not os.path.isdir(dest):
        tmp = os.path.join(releases, f".{sha}.tmp.{os.getpid()}")
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp, mode=0o700)
        with tarfile.open(fileobj=io.BytesIO(_git(repo, "archive", "--format=tar", "HEAD"))) as tar:
            tar.extractall(tmp, filter="data")
        os.rename(tmp, dest)
    previous = current_sha(root)
    link = os.path.join(root, f".current.tmp.{os.getpid()}")
    try:
        os.remove(link)
    except OSError:
        pass
    os.symlink(os.path.join("releases", sha), link)
    os.replace(link, os.path.join(root, "current"))
    os.utime(dest)
    _prune(releases, {sha, previous}, time.time() if now is None else now)
    return sha


def main() -> int:
    repo = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    sha = publish(repo)
    print(f"Record timer now runs {sha}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
