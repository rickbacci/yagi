# Omarchy TV (`richardb.omarchy-tv`)

[![Tests](https://img.shields.io/badge/tests-83%20passed-success)](tests/)
[![Platform](https://img.shields.io/badge/platform-Omarchy%20%7C%20Arch%20Linux-blue)](https://omarchy.org/)
[![Compositor](https://img.shields.io/badge/compositor-Hyprland-lightblue)](https://hyprland.org/)
[![UI Engine](https://img.shields.io/badge/ui-Quickshell%20(QtQuick%20%2F%20QML)-purple)](https://quickshell.outfoxxed.me/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Over-The-Air digital television for **Omarchy** (Arch Linux + Hyprland + Quickshell + MPV). It is a status-bar plugin, a floating live player, and a dual-tuner recorder — not a MythTV backend and not a Kaffeine clone.

---

## What it does

Omarchy TV is a native ATSC 1.0 live-TV suite. Click the antenna on the Omarchy bar, scan your market, and watch in a pinned 16:9 Picture-in-Picture window.

**Live TV.** Tuner 0 dumps the locked ATSC multiplex (exact `+28615` Hz pilot offset) to `live.ts`. A follow process copies that growing file to one windowed MPV (the PiP never opens `dvb://`). The player HUD shows the station, current program, and a short control legend. `j` / `k` surf channels; closing the window (or **Close TV**) wipes the dump and returns the flyout to the channel list.

**Guide.** Open Guide from the bar flyout for a full-width evening grid (6:00 PM–11:00 PM). This is a local template, not live PSIP from the tuner. Click a row to tune that station now; the red button records now.

**Record.** Tuner 1 dumps the live multiplex to `~/Videos/TV` while you keep watching on Tuner 0. Start and stop from the flyout, the HUD (`r` on live TV), or `omarchy-tv record`. Play a finished file from the Recordings library. When that file ends, playback returns to the last live station.

**Pause live.** Tuner 0 is a headless dump into `~/.cache/omarchy/tv/timeshift/live.ts`. The PiP reads a follow pipe of that file so playback does not freeze at EOF. Pause freezes the picture; skip seeks in the dump; `→` at live flashes LIVE rather than filling the bar; `l` seeks the write head. Channel change wipes the dump. Tuner 1 stays free to record. The dump is not a library recording.

**Library cap.** Recordings are pruned oldest-first against an automatic budget (about 20 GB, smaller on tight disks), or a fixed size, or unlimited.

Everything runs as `$USER`. No sudo, no extra daemon you have to babysit for basic watch/record, sockets only under `$XDG_RUNTIME_DIR`.

---

## Why this instead of MythTV / Kaffeine / Tvheadend

- **Omarchy-native UI**: antenna widget, themed `KeyboardPanel`, no foreign toolkit dialogs.
- **Dual-tuner leases**: dump and pause-live on Tuner 0; scan and record on Tuner 1. The PiP never opens DVB. Frontends are released before a new dump so you do not hit `EBUSY`.
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
│  Tuner 0 dump│  Tuner 1 record       │  PiP plays live.ts   │
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
omarchy-tv pause                           # freeze live; dump keeps filling
omarchy-tv live                            # seek dump write head, or retune after a file
omarchy-tv seek 15                         # skip 15s in the live dump or a recording
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

| Key | Live TV | Recording |
| --- | --- | --- |
| `Space` | Pause (dump keeps filling) / Play | Pause / resume |
| `j` / `k` or ↓ / ↑ | Previous / next channel (new dump) | Same — returns to live first |
| ← / → | ±15 s in the dump; last skip toward live seeks the write head | −15 / +15 s; last skip retunes live |
| `l` | Seek the dump write head (live) | Return to live (new dump) |
| `r` | Start or stop a library recording | ignored |
| `f` / double-click | Hyprland fullscreen toggle | same |
| `c` | Cycle subtitles | same |
| Wheel / middle-click | Volume / mute | same |

MPEG-TS files often have no duration. The HUD estimates length from file size (~19.39 Mbps) and counts 15s skips. Catching that end, or EOF, retunes the last live station.

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

## More documentation

- **[DESIGN.md](DESIGN.md)** — layers, tuner leases, DVR vs timeshift, security.
- **[HARDWARE_AND_TROUBLESHOOTING.md](HARDWARE_AND_TROUBLESHOOTING.md)** — Hauppauge dualHD, RF, EBUSY, paths.
- **[AGENTS.md](AGENTS.md)** — invariants for anyone changing the code.
- **[License](LICENSE)** — MIT.
