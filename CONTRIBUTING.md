# Development

User setup is in [README.md](README.md). Why the play path works is `DESIGN.md`. Tuners and RF are `HARDWARE_AND_TROUBLESHOOTING.md`.

## Tests

From the repo root, install the test tools once, then run the suite:

```bash
bash scripts/setup-test-env.sh
python3 -m unittest
python3 bin/yagi status
```

`scripts/setup-test-env.sh` installs python3, luajit (also available as `lua`), psmisc (`fuser`, so the library cap can see a file that is open), nodejs, ffmpeg, mpv, procps, and Qt 6's `qmltestrunner` with the Quick modules. GitHub Actions runs that script and then `python3 -m unittest` on every pull request and every push to `main`. A missing one of those tools fails the suite; it is not a skip. The suite compiles and instantiates `plugin/BarWidget.qml` offscreen, so a missing QML import fails here the same way it fails in the shell. On a machine with a systemd user manager it also checks that a scope leaves the caller's cgroup; that test uses the real `XDG_RUNTIME_DIR`, not the sandbox. The only skip on a normal desktop or in CI is the live ATSC tuner test.

Tests set their own `XDG_*` directories and do not read or write `~/Videos/TV` or `~/.config/yagi`. They also do not put sockets in `/tmp`. They reject a non-item, such as a hover handler or a timer, placed directly in `KeyboardPanel`. That panel's default property only accepts items, and a handler there stops the bar from loading. They also reject an editable text field (`TextField`, `TextInput`, `TextEdit`, `TextArea`) that is not inside a `Loader` whose `active` starts false.

After a QML change, `omarchy restart shell`.

## Run this tree as the plugin

```bash
ln -sfn "$(pwd)" ~/.config/omarchy/plugins/richardb.yagi
omarchy bar put richardb.yagi --section right
omarchy restart shell
```

`omarchy plugin validate` the git root itself. Validating the symlink under `~/.config/omarchy/plugins/` fails because that path is a symlink.

The bar and the picture overlay run the command `yagi`, so `bin/` needs to be on `PATH` for a terminal and for the overlay. `python3 bin/yagi` always uses the script you name. `install` publishes `HEAD` of the directory that contains that script to `~/.local/share/yagi/current`. The record timer runs that copy, not the working tree.

## Picture window

The same rule as in the README, plus the opacity line the rest of the window rules expect:

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
