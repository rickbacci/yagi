#!/bin/bash
# Test tools for python3 -m unittest. Idempotent. Safe to re-run.
set -euo pipefail

if [ "$(id -u)" -eq 0 ]; then
  APT=(apt-get)
else
  APT=(sudo -n apt-get)
fi

"${APT[@]}" update
"${APT[@]}" install -y python3 luajit psmisc nodejs ffmpeg mpv procps

if ! command -v lua >/dev/null 2>&1; then
  ln -sfn "$(command -v luajit)" /usr/local/bin/lua
fi
