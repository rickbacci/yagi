# Development

User setup is in [README.md](README.md). Why the play path works is `DESIGN.md`. Tuners and RF are `HARDWARE_AND_TROUBLESHOOTING.md`.

## Tests

From the repo root, install the test tools once, then run the suite:

```bash
bash scripts/setup-test-env.sh
python3 -m unittest
python3 bin/yagi status
```

`scripts/setup-test-env.sh` installs python3, luajit (also available as `lua`), psmisc (`fuser`, so the library cap can see a file that is open), nodejs, ffmpeg, mpv, procps, and Qt 6's `qmltestrunner` with the Quick modules. GitHub Actions runs that script and then `python3 -m unittest` on every pull request and every push to `main`. A missing one of those tools fails the suite; it is not a skip. The suite instantiates `plugin/BarWidget.qml` and every page offscreen with Qt 6 (`/usr/lib/qt6/bin/qmltestrunner`, or another binary that reports Qt 6). A Qt 5 `qmltestrunner` earlier on `PATH` is not used. If that runner is missing, the failure names `qt6-declarative` / `qt6-declarative-dev-tools`. When pid 1 is systemd, the suite also checks that a scope leaves the caller's cgroup, using the real `XDG_RUNTIME_DIR`. A missing user-manager socket fails that test. It skips only when pid 1 is not systemd. The other skip is the live ATSC tuner test.

Tests set their own `XDG_*` directories and do not read or write `~/Videos/TV` or `~/.config/yagi`. They also do not put sockets in `/tmp`. They reject a non-item, such as a hover handler or a timer, placed directly in `KeyboardPanel`. That panel's default property only accepts items, and a handler there stops the bar from loading. They also reject an editable text field (`TextField`, `TextInput`, `TextEdit`, `TextArea`) that is not inside a `Loader` whose `active` starts false.

After a QML change, `omarchy restart shell`.

## Run this tree as the plugin

```bash
ln -sfn "$(pwd)" ~/.config/omarchy/plugins/richardb.yagi
omarchy bar put richardb.yagi --section right
omarchy restart shell
```

`omarchy plugin validate` the git root itself. Validating the symlink under `~/.config/omarchy/plugins/` fails because that path is a symlink.

The bar and the picture overlay run the command `yagi`, so `bin/` needs to be on `PATH` for a terminal and for the overlay. `python3 bin/yagi` always uses the script you name. Watch, pause, record-now, scan, and the Guide do not need `install`. `install` is optional: it publishes `HEAD` of the directory that contains that script to `~/.local/share/yagi/current` and starts the record timer. That timer runs the published copy, not the working tree, and it is what starts scheduled and series recordings. If it is already on, a plugin update is enough. The timer publishes the new commit on a later tick.

## Picture window

This rule is optional. Yagi pins the small picture itself, and a stock install does not need it. Use it when an older rule pins class `yagi` and fullscreen will not stick. Do not set `pin = true` here. A pin is put back the moment the window leaves fullscreen.

The opacity line is what the rest of the window rules expect:

```lua
o.window({ class = "^yagi$", fullscreen = false }, {
  tag = "-default-opacity",
  float = true,
  keep_aspect_ratio = true,
  border_size = 0,
  size = { "(monitor_h*16/27)", "(monitor_h/3)" },
  opacity = "1 1",
  move = { "(monitor_w-(monitor_h*16/27)-40)", "(monitor_h-(monitor_h/3)-40)" },
})
o.window("yagi", {
  no_shortcuts_inhibit = true,
  tag = "-default-opacity",
  opacity = "1 1",
})
```

```bash
hyprctl reload && hyprctl configerrors
```

## Panel

The shell can open the panel without the bar icon:

```bash
omarchy-shell shell toggle richardb.yagi
```
