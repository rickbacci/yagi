"""The record timer runs a copy of the last commit, never the working tree.

Each commit unpacks to $XDG_DATA_HOME/yagi/releases/<sha>, or to
~/.local/share/yagi/releases/<sha> when XDG_DATA_HOME is unset, and
current points at it. An edit saved halfway in the repo never reaches
a recording.
The git hook runs this file on its own. The repo root goes on the path so
the bounded git capture in engine.procio imports, and nothing else is required.

`omarchy plugin update` is a git pull, and a pull runs no hooks, so each timer
tick also republishes when the source repo's HEAD has moved.
"""

import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
from typing import List, Optional

_ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from engine.procio import capture

def default_root() -> str:
    """The published copy: $XDG_DATA_HOME/yagi, or ~/.local/share/yagi."""
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "yagi")
# A record finish or Guide update can still be running from an older copy.
KEEP_NEWEST = 3
KEEP_SECS = 24 * 3600
TIMER = "yagi-record.timer"
UNITS = ("yagi-record.service", TIMER)


# What the record timer needs from HEAD. Agent notes, Cursor setup, tests,
# and developer scripts stay in the git checkout and out of this copy.
SNAPSHOT_DIRS = (
    "assets/",
    "bin/",
    "engine/",
    "markets/",
    "player/",
    "plugin/",
    "systemd/",
)
SNAPSHOT_FILES = frozenset({
    "CHANGELOG.md",
    "DESIGN.md",
    "HARDWARE_AND_TROUBLESHOOTING.md",
    "LICENSE",
    "README.md",
    "manifest.json",
})
# A secret under an allowed directory still stays out.
_SNAPSHOT_DENY = re.compile(
    r"(^|/)\.env($|\.)|(^|/)id_rsa($|\.)|\.(pem|p12|key)$|(^|/)credentials([^/]|$)|(^|/)secrets?(/|$)",
    re.IGNORECASE,
)


def snapshot_allowed(path: str) -> bool:
    name = path.replace("\\", "/").lstrip("./")
    if not name or _SNAPSHOT_DENY.search(name):
        return False
    if name in SNAPSHOT_FILES:
        return True
    return any(name.startswith(prefix) for prefix in SNAPSHOT_DIRS)


def snapshot_paths(repo: str) -> List[str]:
    """Tracked files publish() unpacks. Everything else in HEAD is left behind."""
    raw = _git(repo, "ls-files", "-z")
    names = []
    for part in raw.split(b"\0"):
        if not part:
            continue
        name = part.decode("utf-8", "surrogateescape")
        if snapshot_allowed(name):
            names.append(name)
    return names


def _git(repo: str, *args: str) -> bytes:
    # CI checks this tree out as another user inside a container. Name this
    # checkout. A star would mark every directory on the machine as safe.
    repo = os.path.abspath(repo)
    result = capture(
        ["git", "-c", f"safe.directory={repo}", "-C", repo, *args],
        max_bytes=64 * 1024 * 1024,
        timeout=120,
        check=True,
    )
    return result.stdout


def current_sha(root: Optional[str] = None) -> str:
    root = default_root() if root is None else root
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


def publish(repo: str, root: Optional[str] = None, now: Optional[float] = None) -> str:
    """Unpack HEAD and point current at it. Returns the short sha."""
    root = default_root() if root is None else root
    sha = _git(repo, "rev-parse", "--short=12", "HEAD").decode().strip()
    releases = os.path.join(root, "releases")
    os.makedirs(releases, mode=0o700, exist_ok=True)
    dest = os.path.join(releases, sha)
    if not os.path.isdir(dest):
        tmp = os.path.join(releases, f".{sha}.tmp.{os.getpid()}")
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp, mode=0o700)
        members = snapshot_paths(repo)
        if not members:
            raise RuntimeError("HEAD has no files for the record-timer snapshot")
        blob = _git(repo, "archive", "--format=tar", "HEAD", *members)
        with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
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


def source_repo(root: Optional[str] = None) -> str:
    root = default_root() if root is None else root
    try:
        with open(os.path.join(root, "source"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def refresh(root: Optional[str] = None) -> Optional[str]:
    """Publish the source repo's HEAD if it moved. Returns the new sha, or None."""
    root = default_root() if root is None else root
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


def install(repo: str, root: Optional[str] = None, units: Optional[str] = None, run=subprocess.run) -> str:
    """Publish HEAD and start the record timer. Returns the sha it runs."""
    root = default_root() if root is None else root
    sha = publish(repo, root)
    units = units or unit_dir()
    os.makedirs(units, exist_ok=True)
    for name in UNITS:
        shutil.copyfile(os.path.join(repo, "systemd", "user", name), os.path.join(units, name))
    run(["systemctl", "--user", "daemon-reload"], check=True)
    run(["systemctl", "--user", "enable", "--now", TIMER], check=True)
    return sha


def uninstall(root: Optional[str] = None, units: Optional[str] = None, run=subprocess.run) -> None:
    """Stop the timer and remove its copies. Recordings and settings stay."""
    root = default_root() if root is None else root
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
