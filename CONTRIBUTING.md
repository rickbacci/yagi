# Development

User setup is in [README.md](README.md). Why the play path works is `DESIGN.md`. Tuners and RF are `HARDWARE_AND_TROUBLESHOOTING.md`.

## Tests

From the repo root, install the test tools once, then run the suite:

```bash
bash scripts/dev-setup.sh
python3 -m unittest
python3 bin/yagi status
python3 scripts/pre_review.py
```

`scripts/dev-setup.sh` is opt-in. It installs python3, luajit (also available as `lua`), psmisc (`fuser`, so the library cap can see a file that is open), nodejs, ffmpeg, mpv, procps, and Qt 6's `qmltestrunner` with the Quick modules, and it enables linger so the user manager exists. Run it when you mean to. Cursor's automatic install hook is `scripts/setup-test-env.sh`, which only checks that those tools are already on `PATH`. GitHub Actions runs `scripts/dev-setup.sh` and then `python3 -m unittest` on every pull request and every push to `main`.

`python3 scripts/pre_review.py` is the check to run before sending a tree for review. It fails if the release snapshot would ship agent or dev files, if a command reads unbounded output or a timeout leaves its process group running, if a broadcast parser trusts a declared count past the bytes it has, or if an automatic agent setup uses sudo, a package manager, or loginctl. It also fails when guide paste is not capped at 256 bytes, when git trusts every directory, when a timeout can signal the caller's own process group, when a missing tuner is described as both tuners being busy, when a missing mpv would crash the player, or when the release copy ignores `$XDG_DATA_HOME`. The same command runs `omarchy plugin validate` (the upstream `omarchy-plugin-validate` script when the `omarchy` command is not installed), `qmllint` on `plugin/*.qml`, and `ruff`. Exit 0 is pass. Anything else prints a FAIL line for each class.

A missing one of those tools fails the suite; it is not a skip. The suite instantiates `plugin/BarWidget.qml` and every page offscreen with Qt 6 (`/usr/lib/qt6/bin/qmltestrunner`, or another binary that reports Qt 6). A Qt 5 `qmltestrunner` earlier on `PATH` is not used. If that runner is missing, the failure names `qt6-declarative` / `qt6-declarative-dev-tools`. When pid 1 is systemd, the suite also checks that a scope leaves the caller's cgroup, using the real `XDG_RUNTIME_DIR`. A missing user-manager socket fails that test. It skips only when pid 1 is not systemd. The other skip is the live ATSC tuner test.

Tests set their own `XDG_*` directories and do not read or write `~/Videos/TV` or `~/.config/yagi`. They also do not put sockets in `/tmp`. They reject a non-item, such as a hover handler or a timer, placed directly in `KeyboardPanel`. That panel's default property only accepts items, and a handler there stops the bar from loading. They also reject an editable text field (`TextField`, `TextInput`, `TextEdit`, `TextArea`) that is not inside a `Loader` whose `active` starts false.

After a QML change, `omarchy restart shell`.

## Run this tree as the plugin

```bash
ln -sfn "$(pwd)" ~/.config/omarchy/plugins/richardb.yagi
omarchy bar put richardb.yagi --section right
omarchy restart shell
```

`omarchy plugin validate` the git root itself. Validating the symlink under `~/.config/omarchy/plugins/` fails because that path is a symlink.

The bar and the picture overlay run the command `yagi`, so `bin/` needs to be on `PATH` for a terminal and for the overlay. `python3 bin/yagi` always uses the script you name. Watch, pause, record-now, scan, and the Guide do not need `install`. `install` is optional: it publishes `HEAD` of the directory that contains that script to `$XDG_DATA_HOME/yagi/current`, or to `~/.local/share/yagi/current` when `XDG_DATA_HOME` is unset, and starts the record timer. That timer runs the published copy, not the working tree, and it is what starts scheduled and series recordings. The timer unit uses the same fallback. If it is already on, a plugin update is enough. The timer publishes the new commit on a later tick.

## Releasing

The version lives only in `manifest.json`. Pushing a tag `v` plus that version (today `v0.1.7`) runs `.github/workflows/release.yml`. The workflow refuses the tag when it does not match `manifest.json`, then publishes a GitHub release whose notes are that version's section of `CHANGELOG.md`.

Check the tag locally before pushing it. This does not create a tag or a release:

```bash
python3 scripts/check-release-tag.py v0.1.7
python3 scripts/check-release-tag.py --notes
```

`scripts/omarchy-plugin-validate` is the script from `basecamp/omarchy` branch `quattro`, path `bin/omarchy-plugin-validate`. `omarchy plugin validate` runs that script. The pre-review check calls the command when `omarchy` is on `PATH`, and otherwise runs this copy, because the runners do not have the Omarchy CLI. It sets `LC_ALL=C` so the id check stays on ASCII.

## Picture window

Yagi places and pins the small picture itself, and a stock install does not need a window rule. Use this rule when an older rule pins class `yagi` and fullscreen will not stick. Do not set `pin = true` here. A pin is put back the moment the window leaves fullscreen.

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
