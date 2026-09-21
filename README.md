# Omarchy TV (`richardb.omarchy-tv`)

[![Platform](https://img.shields.io/badge/platform-Omarchy%20%7C%20Arch%20Linux-blue)](https://omarchy.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

OTA ATSC 1.0 for Omarchy: bar plugin, pinned PiP, dual-tuner record. Not MythTV, not Kaffeine.

Click the antenna, scan, watch 16:9 PiP. Guide is a local evening grid (not live PSIP). Record on Tuner 1 into `~/Videos/TV` while Tuner 0 keeps the live dump. Pause-live is that dump over loopback HTTP (skip is `loadfile` in the same window). Close TV wipes the pause dump; it is not a library recording. Runs as `$USER`.

Why not Myth/Kaffeine: Omarchy chrome, tuner leases, `+28615` Hz pilots, ignore false PSIP `access_controlled`, Hyprland PiP class `omarchy-tv`.

Architecture: `DESIGN.md`. Tuner/RF: `HARDWARE_AND_TROUBLESHOOTING.md`.

```
omarchy-tv/
├── bin/omarchy-tv
├── engine/  player/  plugin/  tests/
├── AGENTS.md  DESIGN.md  HARDWARE_AND_TROUBLESHOOTING.md
└── skills/omarchy-tv/SKILL.md
```

State: `~/.config/omarchy/tv/`. Library: `~/Videos/TV`.

## Quickstart

```bash
ln -sfn ~/Projects/personal/omarchy-tv/plugin ~/.config/omarchy/plugins/richardb.omarchy-tv
omarchy bar put richardb.omarchy-tv --section right
```

`~/.config/hypr/hyprland.lua`:

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

Scan from the bar (or `omarchy-tv scan`), pick a station. **Close TV** brings the list back. Put `bin/` on `PATH`.

## CLI

```bash
omarchy-tv status | scan | scan --full | list | guide
omarchy-tv play "8.1 FOX" | next | prev | stop | sync | pause | live | seek 10 | fullscreen
omarchy-tv record start 8.1 1h | stop | list | play <file> | delete <file>
omarchy-tv favorite toggle "8.1 FOX"
omarchy-tv pref translators off | pref filter favorites | pref library-max auto|20|50|off
```

`pause` is throwaway `live.ts`. `record` is a keepable file. `live` `loadfile`s the dump write head, or retunes after a recording.

## HUD (pointer in the PiP — not the plugin, not Super+K)

| Key | Live TV | Recording |
| --- | --- | --- |
| Space | Pause (dump fills); play stays behind until `l` | Pause / resume |
| j / k or ↓ / ↑ | Banner; tunes after you stop | Commit returns to live |
| ← / → | Skip HTTP playhead (last hop is live, same window) | Skip; last hop retunes live |
| l | Live write head (same window) | Return to live (new dump) |
| r | Library record | ignored |
| Super+F | Fullscreen (unpins first) | same |
| c | Captions | same |
| m / middle-click | Mute this window | same |
| Wheel | Volume | same |
| Super+LMB | Move PiP | same |

MPEG-TS often has no duration; the HUD uses file size. EOF of a recording retunes live.

## Plugin IPC

```bash
omarchy-shell shell broadcast richardb.omarchy-tv play "8.1 FOX"
# also: stop next prev live guide scan reloadChannels
```

Tests: `python3 -m unittest discover tests` (100% before commit).
