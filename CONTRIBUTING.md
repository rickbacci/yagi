# Development

User setup is in [README.md](README.md). Why the play path works is `DESIGN.md`. Tuners and RF are `HARDWARE_AND_TROUBLESHOOTING.md`.

## Tests

From the repo root:

```bash
python3 -m unittest
python3 bin/yagi status
```

Tests set their own `XDG_*` directories and do not read or write `~/Videos/TV` or `~/.config/yagi`. They also do not put sockets in `/tmp`.

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
  pin = true,
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
