#!/bin/bash
# Automatic setup. Cursor runs this from .cursor/environment.json.
# It only checks which tools are already on PATH.
# A developer who wants packages and a user manager runs scripts/dev-setup.sh on purpose.
set -euo pipefail

need=()
for cmd in python3 ffmpeg mpv; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    need+=("$cmd")
  fi
done
if ! command -v luajit >/dev/null 2>&1 && ! command -v lua >/dev/null 2>&1; then
  need+=(luajit)
fi
if [ "${#need[@]}" -gt 0 ]; then
  echo "These tools are not on PATH: ${need[*]}." >&2
  echo "A developer installs them by running scripts/dev-setup.sh on purpose." >&2
fi

# The user manager is already up. Remember its runtime dir for GitHub Actions.
if [ -n "${GITHUB_ENV:-}" ] && [ -S "/run/user/$(id -u)/systemd/private" ]; then
  echo "XDG_RUNTIME_DIR=/run/user/$(id -u)" >> "$GITHUB_ENV"
fi
