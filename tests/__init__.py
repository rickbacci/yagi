"""Tests run against scratch XDG dirs, never the real library, config, or TV.

Run from the repo root: python3 -m unittest
engine.paths reads the environment once, at import, so this runs first.
Tests see two tuners, whatever this machine has.
"""

import atexit
import os
import shutil
import sys
import tempfile
import time

if "engine.paths" in sys.modules:
    raise RuntimeError("engine.paths was imported before the test sandbox")

# Listings in the tests are Eastern. The app itself uses the machine's zone.
os.environ["TZ"] = "America/New_York"
time.tzset()

# /tmp is RAM on some machines. TMPDIR still wins.
_parent = os.environ.get("TMPDIR") or os.path.join(
    os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "omarchy", "tv-test-tmp"
)
os.makedirs(_parent, exist_ok=True)
SANDBOX = tempfile.mkdtemp(prefix="run-", dir=_parent)
atexit.register(shutil.rmtree, SANDBOX, True)

# Sockets need a short path: a private dir inside the real runtime dir when there is one.
_real_run = os.environ.get("XDG_RUNTIME_DIR") or ""
if os.path.isdir(_real_run) and os.access(_real_run, os.W_OK):
    _run = tempfile.mkdtemp(prefix="omarchy-tv-test-", dir=_real_run)
    atexit.register(shutil.rmtree, _run, True)
else:
    _run = os.path.join(SANDBOX, "run")
    os.makedirs(_run, mode=0o700)
os.environ["XDG_RUNTIME_DIR"] = _run

for _var, _name in (
    ("HOME", "home"),
    ("XDG_CONFIG_HOME", "config"),
    ("XDG_CACHE_HOME", "cache"),
    ("XDG_DATA_HOME", "data"),
    ("XDG_VIDEOS_DIR", "Videos"),
    ("TMPDIR", "tmp"),
):
    _path = os.path.join(SANDBOX, _name)
    os.makedirs(_path, mode=0o700)
    os.environ[_var] = _path
tempfile.tempdir = None

import engine.pool  # noqa: E402

engine.pool.adapters = lambda: (0, 1)
