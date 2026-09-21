---
name: omarchy-tv
description: >
  Control Over-The-Air (OTA) television on Omarchy using the Omarchy TV suite
  and Hauppauge dual-tuner hardware. Use when asked to watch live TV, scan
  channels, open the guide, record a station, pause live TV, play a recording,
  or inspect tuners and signal. Triggers: TV, watch TV, live TV, OTA, antenna,
  broadcast, tuner, ATSC, channels, scan channels, DVR, record, timeshift,
  pause live, guide, EPG, recordings.
---

# Omarchy TV Skill

Control live ATSC television on Omarchy (Hyprland + Quickshell + MPV). Project:
`~/Projects/personal/omarchy-tv`. CLI: `~/Projects/personal/omarchy-tv/bin/omarchy-tv`
(or `omarchy-tv` on `PATH`).

## What the app is

A bar plugin plus a floating PiP player. Scan OTA, watch on Tuner 0, record or
pause-live on Tuner 1, play files from `~/Videos/TV`, return to live when a
file ends. Pause live is a 15-minute cache buffer, not a library recording.

Full product description: repo `README.md` and `DESIGN.md`.

## Quick actions

### Watch

```bash
omarchy-tv play "8.1 FOX"
omarchy-tv next
omarchy-tv prev
omarchy-tv stop
omarchy-tv sync          # clear now-playing if the window is already gone
```

### Pause live and return to the tuner

```bash
omarchy-tv pause         # freeze live; second call plays from that moment
omarchy-tv live          # drop timeshift/recording and retune last live
omarchy-tv seek 10       # file/timeshift only
```

Do not use `record` when the user wants to freeze live and continue later.
`record` writes a keepable file into `~/Videos/TV`. Pause writes a throwaway
under `~/.cache/omarchy/tv/timeshift`.

### Record (library)

```bash
omarchy-tv record start "8.1 FOX" 1h
omarchy-tv record stop
omarchy-tv record list
omarchy-tv record play <filename>
omarchy-tv record delete <filename>
omarchy-tv pref library-max auto|20|50|off
```

### Guide, list, favorites

```bash
omarchy-tv list
omarchy-tv guide
omarchy-tv favorite toggle "8.1 FOX"
omarchy-tv pref filter all|favorites
omarchy-tv pref translators off
```

### Scan and tuners

```bash
omarchy-tv status
omarchy-tv scan
omarchy-tv scan --full
femon -H -a 0
```

### Shell IPC

```bash
omarchy-shell shell broadcast richardb.omarchy-tv play "8.1 FOX"
omarchy-shell shell broadcast richardb.omarchy-tv stop
omarchy-shell shell broadcast richardb.omarchy-tv next
omarchy-shell shell broadcast richardb.omarchy-tv prev
omarchy-shell shell broadcast richardb.omarchy-tv live
omarchy-shell shell broadcast richardb.omarchy-tv guide
omarchy-shell shell broadcast richardb.omarchy-tv reloadChannels
```

After plugin QML changes: `omarchy restart shell`. After Close TV / lua HUD
changes: user must close the player and retune.

## Player keys (HUD only)

Do not paint these on the plugin. Super+K is Hyprland’s cheatsheet, not TV.

- Space — pause live / play from buffer, or pause a file
- j / k (or arrows) — surf live, or seek in a file
- l — return to live
- r — start/stop library record (live dvbin only)
- f — compositor fullscreen
- Wheel / middle-click — volume / mute

## Layout

- Project: `~/Projects/personal/omarchy-tv`
- Channels: `~/.config/omarchy/tv/channels.json`
- MPV table: `~/.config/mpv/channels.conf`
- Plugin: `~/.config/omarchy/plugins/richardb.omarchy-tv`
- Recordings: `~/Videos/TV`
- Timeshift: `~/.cache/omarchy/tv/timeshift`

## Invariants

- No sudo / pkexec. Tuner ACLs are the active seat.
- ATSC frequencies keep `+28615` Hz. Never round to `000000`.
- Tuner 0 live; Tuner 1 scan / record / timeshift dump.
- Release DVB frontends before MPV (`EBUSY`).
- IPC sockets via `engine.paths.get_runtime_socket()` in `$XDG_RUNTIME_DIR`.
- Atomic JSON: write `.tmp`, `os.replace`.
- Scan dwell ≥ 1.2 s.
- Plugin: `Color.*` / `Style.*` tokens; no hardcoded key chords.
- Hyprland class `omarchy-tv` is a floated, pinned, aspect-locked PiP.
- Tests: `python3 -m unittest discover tests` must be 100% before commit.
- Do not commit unless the user asked.
