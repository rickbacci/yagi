# Yagi (`richardb.yagi`)

[![Platform](https://img.shields.io/badge/platform-Omarchy%20%7C%20Arch%20Linux-blue)](https://omarchy.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Watch, pause, and record free over-the-air TV from your Omarchy bar with a USB ATSC tuner.

## What you need

- [Omarchy](https://omarchy.org/) (Hyprland and Quickshell on Arch Linux)
- A Linux-supported ATSC 1.0 USB tuner, such as a Hauppauge WinTV-dualHD
- An antenna

## Features

- Scan local stations from the bar, then watch in a pinned 16:9 picture.
- Pause live TV and skip inside that window. Close TV deletes the pause file. It is not a library recording.
- A Guide built only from what each station broadcasts. Search looks at titles and descriptions.
- Record one airing, or every airing of a show, into `~/Videos/TV`.
- Recording the channel you are watching copies the live dump, so it does not take a second tuner. It can start at the top of the show when the pause reaches back that far.
- A channel on the same tower comes up in about a second. Another tower takes about 3 seconds of tuner lock first.
- Runs as your user. No root for the app.

## Why not MythTV or Kaffeine

Those are full TV apps. Yagi is the Omarchy bar. It leases tuners so live TV, a recording, and a scan do not grab the same stick. It tunes the ATSC pilot at `+28615` Hz. OTA stations are unencrypted, but many set the PSIP `access_controlled` bit; Kaffeine treats that as scrambled, and Yagi plays the stream. The picture is a Hyprland window of class `yagi`.

Architecture: `DESIGN.md`. Tuners and RF: `HARDWARE_AND_TROUBLESHOOTING.md`.

```
yagi/
├── manifest.json
├── bin/yagi
├── engine/  player/  plugin/  tests/  markets/
├── AGENTS.md  DESIGN.md  HARDWARE_AND_TROUBLESHOOTING.md
└── skills/yagi/SKILL.md
```

State lives in `~/.config/yagi/`. The library is `~/Videos/TV`.

`markets/cleveland.json` is an example station map: callsigns and network names for one market, typed by hand, because the broadcast does not carry them. Copy it, or a file in the same shape for your market, to `~/.config/yagi/station_map.json`. Without that file, names come from the scan.

## Honesty

Built and tested on one Hauppauge WinTV-dualHD. See Tuners below.

- Two ATSC adapters, shared: live TV, recordings, scans, and Guide updates each take a free one. Recording what you watch shares live TV's tuner; changing to another tower then moves live TV to the free one, or asks you to stop a recording. A one-tuner box can watch, or record, not both. Nothing takes a tuner that is live, recording, or scanning; a Guide update gives way.
- Ad skipping uses Comskip if installed (`omarchy-pkg-aur-add comskip`), otherwise ffmpeg's black-frame and silence detection, which misses more.
- First run: no stations until you scan, no Hidden list until you hide one, no Guide titles until `guide refresh` (what the stations send in PSIP). The engine does not ship a canned lineup. `markets/cleveland.json` is only an example you can copy in.
- Super+K is Omarchy’s keybindings overlay. It does not open this flyout. Use the antenna, or bind `omarchy-shell -q shell toggle richardb.yagi` in your Hyprland config.
- State JSON is not all `0600`.
- Version in `manifest.json` is `0.1.0`. Not a published 1.0.

## Tuners

Yagi needs an ATSC 1.0 tuner that Linux drives itself: one that shows up as `/dev/dvb/adapterN/frontend0` and lists ATSC among its delivery systems (`dvb-fe-tool -a N`). It uses every adapter it finds.

| Tuner | Status |
| --- | --- |
| Hauppauge WinTV-dualHD, ATSC model (`2040:826d`, LGDT3306A + Si2157) | Tested. Two tuners. `lsusb` may name this ID `Hauppauge 955D`. |
| Other LGDT3306A + Si2157 USB sticks (Hauppauge WinTV-HVR-955Q, WinTV-quadHD ATSC) | Same chips and kernel driver; untested. |
| Other ATSC tuners with a Linux DVB driver | Should work; untested. |
| HDHomeRun and other network tuners | No. They have no `/dev/dvb` device. |
| ATSC 3.0 / NextGen TV | No. Linux has no drivers, and many stations encrypt it. |

One tuner watches or records, not both at once, except that recording the channel you watch copies it from live TV. Two is what this is built and tested on. More should work, but that is untested.

### Check your tuner

```bash
lsusb
dvb-fe-tool -a 0
dvb-fe-tool -a 1
```

A tuner Yagi can use lists `ATSC` in its delivery systems and appears as `/dev/dvb/adapterN/frontend0`.

`lsusb` may print `Hauppauge 955D` for ID `2040:826d`. That string is the vendor ID database label. The stick is the WinTV-dualHD ATSC model.

On the tested dualHD, `dvb-fe-tool -a 0` and `-a 1` both report:

- Device: `LG Electronics LGDT3306A VSB/QAM Frontend`
- Delivery systems: `ATSC` and `DVBC/ANNEX_B` (US cable QAM)
- Capabilities: `CAN_8VSB`, `QAM_64`, `QAM_256`
- Frequency range: 54.0 MHz to 858 MHz
- DVB API: 5.12

The chip can do US cable QAM. Yagi tunes ATSC 8VSB only.

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
omarchy plugin add https://github.com/rickbacci/yagi.git
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

Optional, for the Cleveland example map (or your own file in the same shape):

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
| Recordings | ←/→ Recorded or Scheduled · Enter opens a show, then plays · Esc backs out of the show · `x` twice deletes an episode, or on Scheduled stops or removes · Shift+K locks |

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
