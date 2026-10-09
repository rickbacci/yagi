"""The record timer runs a copy of the last commit, never the working tree.

Each commit unpacks to ~/.local/share/yagi/releases/<sha>, and current
points at it. An edit saved halfway in the repo never reaches a recording.
Standard library only: the git hooks run this without the app's environment.

`omarchy plugin update` is a git pull, and a pull runs no hooks, so each timer
tick also republishes when the source repo's HEAD has moved.
"""

import io
import os
import shutil
import subprocess
import sys
import tarfile
import time
from typing import Optional

DEFAULT_ROOT = os.path.expanduser("~/.local/share/yagi")
# A record finish or Guide update can still be running from an older copy.
KEEP_NEWEST = 3
KEEP_SECS = 24 * 3600
TIMER = "yagi-record.timer"
UNITS = ("yagi-record.service", TIMER)


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
    source = os.path.join(root, f".source.tmp.{os.getpid()}")
    with open(source, "w", encoding="utf-8") as f:
        f.write(os.path.realpath(repo))
    os.replace(source, os.path.join(root, "source"))
    return sha


def source_repo(root: str = DEFAULT_ROOT) -> str:
    try:
        with open(os.path.join(root, "source"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def refresh(root: str = DEFAULT_ROOT) -> Optional[str]:
    """Publish the source repo's HEAD if it moved. Returns the new sha, or None."""
    repo = source_repo(root)
    if not repo:
        return None
    try:
        head = _git(repo, "rev-parse", "--short=12", "HEAD").decode().strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    if head == current_sha(root):
        return None
    return publish(repo, root)


def unit_dir() -> str:
    config = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(config, "systemd", "user")


def install(repo: str, root: str = DEFAULT_ROOT, units: Optional[str] = None, run=subprocess.run) -> str:
    """Publish HEAD and start the record timer. Returns the sha it runs."""
    sha = publish(repo, root)
    units = units or unit_dir()
    os.makedirs(units, exist_ok=True)
    for name in UNITS:
        shutil.copyfile(os.path.join(repo, "systemd", "user", name), os.path.join(units, name))
    run(["systemctl", "--user", "daemon-reload"], check=True)
    run(["systemctl", "--user", "enable", "--now", TIMER], check=True)
    return sha


def uninstall(root: str = DEFAULT_ROOT, units: Optional[str] = None, run=subprocess.run) -> None:
    """Stop the timer and remove its copies. Recordings and settings stay."""
    run(["systemctl", "--user", "disable", "--now", TIMER], check=False)
    units = units or unit_dir()
    for name in UNITS:
        try:
            os.remove(os.path.join(units, name))
        except OSError:
            pass
    run(["systemctl", "--user", "daemon-reload"], check=False)
    shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    repo = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    sha = publish(repo)
    print(f"Record timer now runs {sha}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
