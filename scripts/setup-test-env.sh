#!/bin/bash
# Test tools for python3 -m unittest. Idempotent. Safe to re-run.
set -euo pipefail

if [ "$(id -u)" -eq 0 ]; then
  APT=(apt-get)
else
  APT=(sudo -n apt-get)
fi

"${APT[@]}" update
"${APT[@]}" install -y \
  python3 luajit psmisc nodejs ffmpeg mpv procps \
  qt6-declarative-dev-tools \
  qml6-module-qtquick \
  qml6-module-qtquick-controls \
  qml6-module-qtquick-layouts \
  qml6-module-qtquick-window \
  qml6-module-qtquick-templates \
  libqt6svg6 \
  qml6-module-qtqml \
  qml6-module-qtqml-workerscript \
  dbus-user-session

if ! command -v lua >/dev/null 2>&1; then
  ln -sfn "$(command -v luajit)" /usr/local/bin/lua
fi
if [ -x /usr/lib/qt6/bin/qmltestrunner ] && ! command -v qmltestrunner >/dev/null 2>&1; then
  ln -sfn /usr/lib/qt6/bin/qmltestrunner /usr/local/bin/qmltestrunner
fi

# A user manager lets the cgroup test run. Machines without systemd (the
# socket never appears) still skip that one test.
if [ -d /run/systemd/system ] && command -v systemctl >/dev/null 2>&1; then
  uid="$(id -u)"
  sudo -n mkdir -p "/run/user/${uid}"
  sudo -n chown "${uid}:$(id -g)" "/run/user/${uid}"
  sudo -n chmod 700 "/run/user/${uid}"
  sudo -n loginctl enable-linger "$(id -un)" || true
  sudo -n systemctl start "user@${uid}.service" || true
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
    if [ -S "/run/user/${uid}/systemd/private" ]; then
      break
    fi
    sleep 0.2
  done
  if [ ! -S "/run/user/${uid}/systemd/private" ]; then
    echo "systemd is pid 1 but user@${uid}.service has no manager socket" >&2
    exit 1
  fi
  if [ -n "${GITHUB_ENV:-}" ]; then
    echo "XDG_RUNTIME_DIR=/run/user/${uid}" >> "$GITHUB_ENV"
  fi
fi
