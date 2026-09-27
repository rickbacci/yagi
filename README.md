# Yagi (`richardb.yagi`)

[![Platform](https://img.shields.io/badge/platform-Omarchy%20%7C%20Arch%20Linux-blue)](https://omarchy.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

OTA ATSC 1.0 for Omarchy: bar plugin, pinned PiP, dual-tuner record. Not MythTV, not Kaffeine.

Click the antenna, scan, watch 16:9 PiP. The Guide schedule is only what each station broadcasts; the record timer reads it on a free tuner every few hours. Search looks at titles and descriptions. Record into `~/Videos/TV` on whichever tuner is free, one airing (Record) or every airing (Record series). A channel on the tower you are watching is copied out of the live dump instead: no second tuner, and it starts at the top of the show when the pause reaches back that far; back-to-back episodes split into one file each and ad breaks are skipped on playback. Pause-live is the live dump, the whole tower, read once through a fifo. Skip seeks inside the same window. A channel on the same tower comes up in about a second; another tower takes about 3 s of tuner lock first. Close TV wipes the pause dump; it is not a library recording. Runs as `$USER`.

Why not Myth/Kaffeine: Omarchy chrome, tuner leases, `+28615` Hz pilots, ignore false PSIP `access_controlled`, Hyprland PiP class `yagi`.

Architecture: `DESIGN.md`. Tuner/RF: `HARDWARE_AND_TROUBLESHOOTING.md`. Leftover work: `WHATS_LEFT.md`.

```
yagi/
├── manifest.json
├── bin/yagi
├── engine/  player/  plugin/  tests/  markets/
├── AGENTS.md  DESIGN.md  HARDWARE_AND_TROUBLESHOOTING.md  WHATS_LEFT.md
└── skills/yagi/SKILL.md
```

State: `~/.config/yagi/`. Library: `~/Videos/TV`. Optional `station_map.json` (copy `markets/cleveland.json` there for that RF map); without it, names come from the scan.

## Honesty

Built and tested on one Hauppauge WinTV-dualHD. See Tuners below.

- Two ATSC adapters, shared: live TV, recordings, scans, and Guide updates each take a free one. Recording what you watch shares live TV's tuner; changing to another tower then moves live TV to the free one, or asks you to stop a recording. A one-tuner box can watch, or record, not both. Nothing takes a tuner that is live, recording, or scanning; a Guide update gives way.
- Ad skipping uses Comskip if installed (`omarchy-pkg-aur-add comskip`), otherwise ffmpeg's black-frame and silence detection, which misses more.
- First run: no stations until you scan, no Hidden list until you hide one, no Guide titles until `guide refresh` (what the stations send in PSIP). There is no canned Cleveland lineup in the engine.
- Super+K is Omarchy’s keybindings overlay. It does not open this flyout. Use the antenna, or bind `omarchy-shell -q shell toggle richardb.yagi` (this box: Super+Shift+T in `~/.config/hypr/bindings.lua`).
- State JSON is not all `0600`.
- Version in `manifest.json` is `0.1.0`. Not a published 1.0.

## Tuners

Yagi needs an ATSC 1.0 tuner that Linux drives itself: one that shows up as `/dev/dvb/adapterN/frontend0` and lists ATSC among its delivery systems (`dvb-fe-tool -a N`). It uses every adapter it finds.

| Tuner | Status |
| --- | --- |
| Hauppauge WinTV-dualHD, ATSC model (`2040:826d`, LGDT3306A + Si2157) | Tested. Two tuners. |
| Other LGDT3306A + Si2157 USB sticks (Hauppauge WinTV-HVR-955Q, WinTV-quadHD ATSC) | Same chips and kernel driver; untested. |
| Other ATSC tuners with a Linux DVB driver | Should work; untested. |
| HDHomeRun and other network tuners | No. They have no `/dev/dvb` device. |
| ATSC 3.0 / NextGen TV | No. Linux has no drivers, and many stations encrypt it. |

One tuner watches or records, not both at once, except that recording the channel you watch copies it from live TV. Two is what this is built and tested on. More should work, but that is untested.

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
omarchy plugin add https://example.com/yagi.git
omarchy plugin enable richardb.yagi
omarchy bar put richardb.yagi --section right
omarchy restart shell
~/.config/omarchy/plugins/richardb.yagi/bin/yagi install
```

`install` starts the record timer, which schedules recordings and refreshes the Guide. It runs a copy of the plugin's last commit and picks up each `omarchy plugin update` on its next tick. `yagi status` shows whether it is on. Before `omarchy plugin remove`, run `yagi uninstall`; recordings and settings stay.

Local development (this tree as the plugin dir):

```bash
ln -sfn "$(pwd)" ~/.config/omarchy/plugins/richardb.yagi
omarchy bar put richardb.yagi --section right
omarchy restart shell
```

The bar finds `bin/yagi` next to that plugin dir. Put `bin/` on `PATH` for a terminal and for the HUD (`yagi` from lua).

`omarchy plugin validate` the **real** git root. Validating the `~/.config/omarchy/plugins/…` symlink fails: the start path is a symlink.

`~/.config/hypr/hyprland.lua` (same chrome as Omarchy PiP: float, pin, 16:9, bottom-right, height `monitor/3`):

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

Scan from the bar (or `yagi scan`), pick a station. Then `yagi guide refresh`, or let the record timer do it.

Optional, this RF map only:

```bash
mkdir -p ~/.config/yagi
cp markets/cleveland.json ~/.config/yagi/station_map.json
```

## CLI

```bash
yagi status | scan | scan --full | list | guide | guide refresh | guide search Browns
yagi play "8.1 FOX" | next | prev | stop | sync | pause | live | seek 10 | fullscreen
yagi record start 8.1 1h | stop | list | play <file> | delete <file>
yagi series | series add <station> --title "M*A*S*H" --channel 19.2 | series remove <id> | series keep <id> 30
yagi record keep <file> | unkeep <file> | finish | due
yagi favorite toggle 8.1
yagi signal | signal watch | signal check 8.1 --seconds 60
yagi pref filter favorites|all|hidden | pref library-max auto|50|100|250|off
yagi hidden list | hidden hide 19.1 | hidden show 19.1
```

`pause` is throwaway `live.ts`, the whole tower (about 8.7 GB an hour while the TV is open). The writer stops when that file is an hour of air ahead of the playhead. `record` is a keepable file. `live` seeks the dump write head, or retunes after a recording. A channel on the same tower switches tracks in the same picture; another tower retunes the open tuner and reloads the same window.

## Panel keys

| Where | Keys |
| --- | --- |
| Everywhere | j/k or ↑/↓ move · Enter picks · Esc closes · `g` Guide · `v` Recordings · `f` Favorites · `a` All · Shift+S scan |
| Channels | Enter watches (the TV window takes focus) · `r` records the station |
| Guide | arrows move in the grid · Enter opens the card, again watches if on now, else records · `/` search (Enter or ↓ to the first match, then ↑/↓ step) · `s` Grid or Shows · `r` Record · `a` Record series |
| Recordings | ←/→ Recorded or Scheduled · Enter plays · `x` twice deletes, or on Scheduled stops or removes · Shift+K locks |

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
omarchy-shell shell toggle richardb.yagi
omarchy-shell shell broadcast richardb.yagi play "8.1 FOX"
# also: stop next prev live guide scan reloadChannels open close show hide
```

Tests: `python3 -m unittest` from the repo root. They run in scratch XDG dirs and never touch your library, config, or a running TV.
