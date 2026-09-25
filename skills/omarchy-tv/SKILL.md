---
name: omarchy-tv
description: >
  Control OTA ATSC TV on Omarchy (bar plugin, PiP, Hauppauge dual tuner).
  Use when asked to watch live TV, scan, open the guide, record, pause live,
  play a recording, or inspect tuners. Triggers: TV, live TV, OTA, ATSC,
  tuner, scan, DVR, timeshift, pause live, EPG, HUD, recordings.
---

# Omarchy TV

Project `~/Projects/personal/omarchy-tv`. CLI `omarchy-tv` (`PATH` or `bin/`). Rules: `AGENTS.md`. Facts: `MEMORY.md`.

**Tuners** are one pool (`engine/pool.py`): live prefers 0, work prefers 1, a Guide update gives way. `omarchy-tv status` shows both.

**Play path:** The live tuner dumps `live.ts`. Detached `follow_ts` copies it onto a fifo. The window reads that fifo once as `fd://0` (one read end; opening the path steals a non-aligned prefix). Channel change is the only `loadfile`, and it opens near the live edge and catches up. Skip and live SEEK the control socket. Pause freezes the cursor. Play behind paces at the measured dump rate, and that gap holds until you skip. mpv keeps a few seconds of readahead so the picture does not starve. A skip marks a TS discontinuity and then `drop-buffers` so that readahead is not the old picture. The HUD does not send `drop-buffers`. Behind is file end minus the live cursor, at that rate. The back arrow seeks from the live cursor. HUD `play` must not quit this mpv. One window.

## CLI

```bash
omarchy-tv play "8.1 FOX" | next | prev | stop | sync | pause | live | seek 10
omarchy-tv record start "8.1 FOX" 1h | stop | list | play <file> | delete <file>
omarchy-tv record later | unlater | all | unall | limit | keep | unkeep | due | finish
omarchy-tv list | guide | guide refresh | guide search Browns | status | scan | scan --full
omarchy-tv favorite toggle "8.1 FOX"
omarchy-tv pref filter favorites|all|hidden | pref library-max auto|50|100|250|off
omarchy-tv hidden list | hidden hide 19.1 | hidden show 19.1
omarchy-shell shell broadcast richardb.omarchy-tv play "8.1 FOX"   # also: stop next prev live guide reloadChannels open close toggle
```

A station with no video or audio ID is dumped as the whole channel group once; the next dump is just that station. Guide: search (titles and descriptions), time-of-day tabs, one row per show with Watch / Record / Record all. The record timer (`record due`, every minute) starts queued shows, joins back-to-back episodes into one run, and launches `record finish` to split runs and mark ads. After HUD lua: Close TV and retune.

## Keys

Panel (Super+Shift+T): j/k move, Enter picks, Esc closes, `g` Guide, `v` Recordings. Guide: h/l time tabs, `/` search, `r` record one, `a` Record all. Recordings: `x` twice deletes, Shift+K locks. Picking a channel or recording focuses the TV window (`omarchy-tv focus`).

TV window:

Space pause / play still behind · `l` live · ←/→ skip 10s · ↑/↓ 1 minute · PgUp/PgDn next/last ad break (games never auto-skip) · inside the last 10s, → is live · j/k channel · r record · y save the pause · c captions · m / middle-click mute · wheel volume.

## Paths

`~/.config/omarchy/tv/` channels, guide, state, optional `station_map.json` · `~/.config/mpv/channels.conf` · plugin `~/.config/omarchy/plugins/richardb.omarchy-tv` · IPC `$XDG_RUNTIME_DIR/omarchy-tv-mpv.sock`. First run is empty. Cleveland RF names: `markets/cleveland.json`.

## If pause / skip / HUD is wrong

1. This machine’s `mpv --version` / manpage — not a wiki.
2. Probe the socket **before** editing lua: live `path` is `fd://0`; never `dvb://`. Then `pause` and video width. Skip and read the path again. A new path means the window reopened.
3. lua loads at mpv start. Not fixed until they see it.
4. Do not ship another overlay for a demuxer or path bug. Probe the socket first.
