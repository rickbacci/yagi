# Omarchy TV (`richardb.omarchy-tv`)

[![Tests](https://img.shields.io/badge/tests-84%20passed-success)](tests/)
[![Platform](https://img.shields.io/badge/platform-Omarchy%20%7C%20Arch%20Linux-blue)](https://omarchy.org/)
[![Compositor](https://img.shields.io/badge/compositor-Hyprland-lightblue)](https://hyprland.org/)
[![UI Engine](https://img.shields.io/badge/ui-Quickshell%20(QtQuick%20%2F%20QML)-purple)](https://quickshell.outfoxxed.me/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Over-The-Air digital television for **Omarchy** (Arch Linux + Hyprland + Quickshell + MPV). It is a status-bar plugin, a floating live player, and a dual-tuner recorder — not a MythTV backend and not a Kaffeine clone.

---

## What it does

Omarchy TV is a native ATSC 1.0 live-TV suite. Click the antenna on the Omarchy bar, scan your market, and watch in a pinned 16:9 Picture-in-Picture window.

**Live TV.** Tuner 0 locks an ATSC frequency (exact `+28615` Hz pilot offset) and MPV plays the transport stream. The player HUD shows the station, current program, and a short control legend. `j` / `k` surf channels; closing the window (or **Close TV**) clears now-playing so the flyout returns to the channel list.

**Guide.** The flyout Guide shows now and next for each station. The engine already keeps 6:00 PM–11:00 PM half-hour blocks for the major Cleveland networks so a wider, scrollable evening grid can replace the one-slot pager.

**Record.** Tuner 1 dumps the live multiplex to `~/Videos/TV` while you keep watching on Tuner 0. Start and stop from the flyout, the HUD (`r` on live TV), or `omarchy-tv record`. Play a finished file from the Recordings library. When that file ends, playback returns to the last live station.

**Pause live.** Pause freezes the picture and starts a 15-minute throwaway buffer on Tuner 1. Play continues from that moment instead of jumping to the live broadcast. The buffer lives in cache (`~/.cache/omarchy/tv/timeshift`), is not part of the recordings library, and is deleted when you go live, change channels, or close TV. Seek to the end of a recording or timeshift buffer also returns to the live tuner (`l` on the HUD, or the Live control).

**Library cap.** Recordings are pruned oldest-first against an automatic budget (about 20 GB, smaller on tight disks), or a fixed size, or unlimited.

Everything runs as `$USER`. No sudo, no extra daemon you have to babysit for basic watch/record, sockets only under `$XDG_RUNTIME_DIR`.

---

## Why this instead of MythTV / Kaffeine / Tvheadend

- **Omarchy-native UI**: antenna widget, themed `KeyboardPanel`, no foreign toolkit dialogs.
- **Dual-tuner leases**: watch on Tuner 0; scan, record, and pause-live dumps on Tuner 1. Frontends are released before MPV takes the device so you do not hit `EBUSY`.
- **Exact ATSC pilots**: frequencies are `nominal + 28615` Hz, not round MHz centers.
- **Honest OTA**: PSIP `access_controlled` bits are ignored; unencrypted ATSC streams play without a fake scramble padlock.
- **PiP that belongs on Hyprland**: class `omarchy-tv`, floated, pinned, aspect locked.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│              Omarchy Bar Widget (KeyboardPanel)             │
│       (~/.config/omarchy/plugins/richardb.omarchy-tv)       │
│   Channels · Guide · Recordings · now-playing / Close TV    │
└──────────────────────────────┬──────────────────────────────┘
                               │ FileView JSON + IpcHandler
┌──────────────────────────────▼──────────────────────────────┐
│                    Omarchy TV Core (Python)                 │
│  scanner · enrichment · guide · DVR · timeshift · tuners    │
├──────────────┬───────────────────────┬──────────────────────┤
│  /dev/dvb/*  │  ~/Videos/TV library  │  MPV + tv_hud.lua    │
│  Tuner 0 live│  cache timeshift buf  │  PiP, JSON IPC       │
└──────────────┴───────────────────────┴──────────────────────┘
```

---

## Project layout

```
omarchy-tv/
├── README.md
├── DESIGN.md
├── HARDWARE_AND_TROUBLESHOOTING.md
├── AGENTS.md
├── bin/omarchy-tv                 # CLI
├── engine/                        # scan, tuners, EPG, DVR, timeshift, paths
├── player/controller.py           # MPV launch, live / file / pause-live
├── player/scripts/tv_hud.lua      # on-video HUD and player keys
├── plugin/                        # Quickshell bar widget
│   ├── BarWidget.qml
│   ├── Model.js
│   └── manifest.json
├── skills/omarchy-tv/SKILL.md     # agent skill
└── tests/
```

State files live under `~/.config/omarchy/tv/` (`channels.json`, `guide.json`, `player_state.json`, `recordings.json`, …). The MPEG library is `~/Videos/TV` (or `$XDG_VIDEOS_DIR/TV`).

---

## Quickstart

### 1. Link the plugin

```bash
ln -sfn ~/Projects/personal/omarchy-tv/plugin ~/.config/omarchy/plugins/richardb.omarchy-tv
omarchy bar put richardb.omarchy-tv --section right
```

### 2. Hyprland window rule

In `~/.config/hypr/hyprland.lua`:

```lua
o.window("omarchy-tv", {
  float = true,
  pin = true,
  size = { 720, 405 },
  keep_aspect_ratio = true,
  opacity = "1 1",
  move = { "(monitor_w-window_w-40)", "(monitor_h-window_h-40)" },
})
```

```bash
hyprctl reload && hyprctl configerrors
```

### 3. Scan and watch

1. Click the TV icon on the bar.
2. Run **Scan OTA Channels** (or `omarchy-tv scan`).
3. Pick a station. The list hides while you watch; **Close TV** (or close the PiP) brings it back.

Put `bin/` on your `PATH`, or invoke `~/Projects/personal/omarchy-tv/bin/omarchy-tv`.

---

## Command-line interface

```bash
omarchy-tv status                          # tuners + player
omarchy-tv scan                            # fast VHF-High + UHF
omarchy-tv scan --full                     # all 68 frequencies
omarchy-tv list                            # saved channels
omarchy-tv guide                           # now/next EPG dump
omarchy-tv play "8.1 FOX"
omarchy-tv next | prev | stop
omarchy-tv pause                           # freeze live / resume timeshift
omarchy-tv live                            # leave a recording or timeshift
omarchy-tv seek 10                         # relative seconds in a file
omarchy-tv sync                            # drop stale now-playing if the window is gone
omarchy-tv record start 8.1 1h
omarchy-tv record stop
omarchy-tv record list | status | play <file> | delete <file>
omarchy-tv favorite toggle "8.1 FOX"
omarchy-tv pref translators off
omarchy-tv pref filter favorites
omarchy-tv pref library-max auto|20|50|off
```

---

## Player HUD keys

These chords are painted on the MPV HUD only. The shell plugin does not duplicate them.

| Key | Live TV | Recording / timeshift |
| --- | --- | --- |
| `Space` | Pause live (start buffer) / Play from pause | Pause / resume |
| `j` / `k` or ↓ / ↑ | Previous / next channel | Seek −10 / +10 s |
| ← / → | — | Seek −10 / +10 s |
| `l` | — | Return to live |
| `r` | Start or stop a library recording | ignored |
| `f` / double-click | Hyprland fullscreen toggle | same |
| `c` | Cycle subtitles | same |
| Wheel / middle-click | Volume / mute | same |

Seeking past the end of a file, or hitting EOF, retunes the last live station.

---

## Shell plugin and IPC

The bar widget is `richardb.omarchy-tv`. Flyout chrome: **Guide**, **Recordings**, All / Favorites, translator hide, star, **Pause**, **Record** / **Stop**, **Close TV**.

```bash
omarchy-shell shell broadcast richardb.omarchy-tv play "8.1 FOX"
omarchy-shell shell broadcast richardb.omarchy-tv stop
omarchy-shell shell broadcast richardb.omarchy-tv next
omarchy-shell shell broadcast richardb.omarchy-tv prev
omarchy-shell shell broadcast richardb.omarchy-tv live
omarchy-shell shell broadcast richardb.omarchy-tv guide
omarchy-shell shell broadcast richardb.omarchy-tv scan
omarchy-shell shell broadcast richardb.omarchy-tv reloadChannels
```

Hyprland example:

```lua
o.bind("XF86AudioNext", "exec", "omarchy-shell shell broadcast richardb.omarchy-tv next")
o.bind("XF86AudioPrev", "exec", "omarchy-shell shell broadcast richardb.omarchy-tv prev")
o.bind("SUPER, F12",   "exec", "omarchy-shell shell broadcast richardb.omarchy-tv stop")
```

---

## Tests

```bash
cd ~/Projects/personal/omarchy-tv
python3 -m unittest discover tests -v
```

Must pass 100% before a commit (`AGENTS.md`).

---

## Planned

Shipped behavior is listed above. Still to land in the flyout:

- **Wider panels** sized from the display (channel list about a third of the screen, guide about half), instead of the 380×560 token cap used to match other right-side cards.
- **Scrollable evening grid** using the engine’s 6:00 PM–11:00 PM program blocks (three to six half-hour columns by width).

The PiP video window size is already correct.

---

## More documentation

- **[DESIGN.md](DESIGN.md)** — layers, tuner leases, DVR vs timeshift, security.
- **[HARDWARE_AND_TROUBLESHOOTING.md](HARDWARE_AND_TROUBLESHOOTING.md)** — Hauppauge dualHD, RF, EBUSY, paths.
- **[AGENTS.md](AGENTS.md)** — invariants for anyone changing the code.
- **[License](LICENSE)** — MIT.
