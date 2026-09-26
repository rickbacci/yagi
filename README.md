# Omarchy TV (`richardb.omarchy-tv`)

[![Platform](https://img.shields.io/badge/platform-Omarchy%20%7C%20Arch%20Linux-blue)](https://omarchy.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

OTA ATSC 1.0 for Omarchy: bar plugin, pinned PiP, dual-tuner record. Not MythTV, not Kaffeine.

Click the antenna, scan, watch 16:9 PiP. The Guide schedule is only what each station broadcasts; the record timer reads it on a free tuner every few hours. Search looks at titles and descriptions. Record into `~/Videos/TV` on whichever tuner is free, one show or every airing (Record all); back-to-back episodes split into one file each and ad breaks are skipped on playback. Pause-live is the live dump, the whole tower, read once through a fifo. Skip seeks inside the same window. A channel on the same tower comes up in about a second; another tower takes about 3 s of tuner lock first. Close TV wipes the pause dump; it is not a library recording. Runs as `$USER`.

Why not Myth/Kaffeine: Omarchy chrome, tuner leases, `+28615` Hz pilots, ignore false PSIP `access_controlled`, Hyprland PiP class `omarchy-tv`.

Architecture: `DESIGN.md`. Tuner/RF: `HARDWARE_AND_TROUBLESHOOTING.md`. Leftover work: `WHATS_LEFT.md`.

```
omarchy-tv/
├── manifest.json
├── bin/omarchy-tv
├── engine/  player/  plugin/  tests/  markets/
├── AGENTS.md  DESIGN.md  HARDWARE_AND_TROUBLESHOOTING.md  WHATS_LEFT.md
└── skills/omarchy-tv/SKILL.md
```

State: `~/.config/omarchy/tv/`. Library: `~/Videos/TV`. Optional `station_map.json` (copy `markets/cleveland.json` there for that RF map); without it, names come from the scan.

## Honesty

This is a DualHD-shaped appliance, not a generic PVR.

- Two ATSC adapters, shared: live TV, recordings, scans, and Guide updates each take a free one. A one-tuner box can watch, or record, not both. Nothing takes a tuner that is live, recording, or scanning; a Guide update gives way.
- Ad skipping uses Comskip if installed (`omarchy-pkg-aur-add comskip`), otherwise ffmpeg's black-frame and silence detection, which misses more.
- First run: no stations until you scan, no Hidden list until you hide one, no Guide titles until `guide refresh` (what the stations send in PSIP). There is no canned Cleveland lineup in the engine.
- Super+K is Omarchy’s keybindings overlay. It does not open this flyout. Use the antenna, or bind `omarchy-shell -q shell toggle richardb.omarchy-tv` (this box: Super+Shift+T in `~/.config/hypr/bindings.lua`).
- State JSON is not all `0600`.
- Version in `manifest.json` is `0.1.0`. Not a published 1.0.

## Install

Omarchy (Hyprland + Quickshell). Unprivileged `$USER`. No `sudo` for the app. Tuner access is the active seat’s ACL, not the `video` group.

```bash
sudo pacman -S --needed mpv v4l-utils psmisc procps-ng python
```

`dvbv5-scan` and `dvb-fe-tool` come from `v4l-utils`. `fuser` is `psmisc`. `pgrep` is `procps-ng`. The live dump is plain Python on the DVB device files; mpv plays, and records. `femon` is optional troubleshooting, not a runtime dependency.

```bash
getfacl /dev/dvb/adapter0/frontend0   # expect user:<you>:rw-
getfacl /dev/dvb/adapter1/frontend0
loginctl show-session $(loginctl | awk '/seat0/{print $1}') -p Active
```

If those frontends are `---` for your user, log out and in on seat0. Do not chmod them as root to “fix” it.

A plugin is a git repo with `manifest.json` at the git root (`entryPoints.barWidget` is `plugin/BarWidget.qml`).

```bash
omarchy plugin add https://example.com/omarchy-tv.git
omarchy plugin enable richardb.omarchy-tv
omarchy bar put richardb.omarchy-tv --section right
omarchy restart shell
```

Local development (this tree as the plugin dir):

```bash
ln -sfn "$(pwd)" ~/.config/omarchy/plugins/richardb.omarchy-tv
omarchy bar put richardb.omarchy-tv --section right
omarchy restart shell
```

The bar finds `bin/omarchy-tv` next to that plugin dir. Put `bin/` on `PATH` for a terminal and for the HUD (`omarchy-tv` from lua).

`omarchy plugin validate` the **real** git root. Validating the `~/.config/omarchy/plugins/…` symlink fails: the start path is a symlink.

`~/.config/hypr/hyprland.lua` (same chrome as Omarchy PiP: float, pin, 16:9, bottom-right, height `monitor/3`):

```lua
o.window({ class = "^omarchy-tv$", fullscreen = false }, {
  tag = "-default-opacity",
  float = true,
  pin = true,
  keep_aspect_ratio = true,
  border_size = 0,
  size = { "(monitor_h*16/27)", "(monitor_h/3)" },
  opacity = "1 1",
  move = { "(monitor_w-(monitor_h*16/27)-40)", "(monitor_h-(monitor_h/3)-40)" },
})
o.window("omarchy-tv", {
  no_shortcuts_inhibit = true,
  tag = "-default-opacity",
  opacity = "1 1",
})
```

```bash
hyprctl reload && hyprctl configerrors
```

Scan from the bar (or `omarchy-tv scan`), pick a station. Then `omarchy-tv guide refresh`, or let the record timer do it.

Optional, this RF map only:

```bash
mkdir -p ~/.config/omarchy/tv
cp markets/cleveland.json ~/.config/omarchy/tv/station_map.json
```

## CLI

```bash
omarchy-tv status | scan | scan --full | list | guide | guide refresh | guide search Browns
omarchy-tv play "8.1 FOX" | next | prev | stop | sync | pause | live | seek 10 | fullscreen
omarchy-tv record start 8.1 1h | stop | list | play <file> | delete <file>
omarchy-tv record all <station> --title "M*A*S*H" --channel 19.2 | unall <id> | limit <id> 30
omarchy-tv record keep <file> | unkeep <file> | finish | due
omarchy-tv favorite toggle "8.1 FOX"
omarchy-tv pref filter favorites|all|hidden | pref library-max auto|50|100|250|off
omarchy-tv hidden list | hidden hide 19.1 | hidden show 19.1
```

`pause` is throwaway `live.ts`, the whole tower (about 8.7 GB an hour while the TV is open). The writer stops when that file is an hour of air ahead of the playhead. `record` is a keepable file. `live` seeks the dump write head, or retunes after a recording. A channel on the same tower switches tracks in the same picture; another tower retunes the open tuner and reloads the same window.

## Panel keys

| Where | Keys |
| --- | --- |
| Everywhere | j/k or ↑/↓ move · Enter picks · Esc closes · `g` Guide · `v` Recordings · `f` Favorites · `a` All · Shift+S scan |
| Channels | Enter watches (the TV window takes focus) · `r` records the station |
| Guide | h/l or ←/→ time tabs · `/` search (Enter or ↓ back to the list) · Enter watches if on now, else records · `r` record this one · `a` Record all |
| Recordings | Enter plays · `x` twice deletes · Shift+K locks |

## HUD (the TV window has focus — not the plugin, not Super+K)

| Key | Live TV | Recording |
| --- | --- | --- |
| Space | Pause (writer stops an hour ahead); play stays behind until `l` | Pause / resume |
| ← / → | Skip 10s (inside the last 10s, → is live) | Skip; ad breaks jump once (not in games), ← goes back into one |
| ↑ / ↓ | Skip 1 minute | same |
| PgUp / PgDn | ignored | End of the next ad break / start of the last one |
| j / k | Channel down / up (same tower: the old picture holds about a second) | ignored |
| l | Live write head (same window) | Return to live (new dump) |
| r | Record this station | ignored |
| y | Save the paused stretch to Recordings | ignored |
| Super+F | Fullscreen (unpins first) | same |
| c | Captions | same |
| m / middle-click | Mute this window | same |
| Wheel | Volume | same |
| Super+LMB | Move PiP | same |

Until the picture has a frame, the top bar and the bottom line stay up and the middle stays empty. After a frame, they hide on their own. MPEG-TS often has no duration; the HUD uses file size. EOF of a recording retunes live. Channel changes are the flyout list.

## Plugin IPC

```bash
omarchy-shell shell toggle richardb.omarchy-tv
omarchy-shell shell broadcast richardb.omarchy-tv play "8.1 FOX"
# also: stop next prev live guide scan reloadChannels open close show hide
```

Tests: `TMPDIR="${XDG_CACHE_HOME:-$HOME/.cache}/omarchy/tv-test-tmp" python3 -m unittest discover tests`
