---
name: yagi
description: >
  Control OTA ATSC TV on Omarchy (bar plugin, PiP, Hauppauge dual tuner).
  Use when asked to watch live TV, scan, open the guide, record, pause live,
  play a recording, or inspect tuners. Triggers: TV, live TV, OTA, ATSC,
  tuner, scan, DVR, timeshift, pause live, EPG, HUD, recordings.
---

# Yagi

Project `~/Projects/personal/yagi`. CLI `yagi` (`PATH` or `bin/`). Rules: `AGENTS.md`. Facts: `MEMORY.md`.

**Tuners** are one pool (`engine/pool.py`): live prefers 0, work prefers 1, a Guide update gives way. `yagi status` shows both.

**Play path:** `engine/tower_dump.py` holds the live tuner open and dumps the whole tower into `live.ts` (not mpv; recordings still are). Detached `follow_ts` copies it onto a fifo. The window reads that fifo once as `fd://0` (one read end; opening the path steals a non-aligned prefix), probing 2 MB. Same-tower zap: `tv-program` makes the HUD pick that station's tracks by program id, no retune, no reload. Another tower: `tune <Hz>` on the dump socket, about 3 s of lock, then the only `loadfile`, which opens near the live edge and catches up. Skip and live SEEK the control socket. Pause freezes the cursor. Play behind paces at the measured dump rate, and that gap holds until you skip. mpv keeps a few seconds of readahead so the picture does not starve. A skip marks a TS discontinuity and then `drop-buffers` so that readahead is not the old picture. The HUD sends `drop-buffers` only after a same-tower track switch, since each station keeps its own clock. Behind is file end minus the live cursor, at that rate. The back arrow seeks from the live cursor. HUD `play` must not quit this mpv. One window.

## CLI

```bash
yagi play "8.1 FOX" | next | prev | stop | sync | pause | live | seek 10
yagi record start "8.1 FOX" 1h | stop | list | play <file> | delete <file>
yagi record later | unlater | keep | unkeep | due | finish
yagi series | series add <station> --title T --channel 19.2 | series remove <id> | series keep <id> 10
yagi list | guide | guide refresh | guide search Browns | status | scan | scan --full
yagi favorite toggle 8.1
yagi pref filter favorites|all|hidden | pref library-max auto|50|100|250|off
yagi hidden list | hidden hide 19.1 | hidden show 19.1
omarchy-shell shell broadcast richardb.yagi play "8.1 FOX"   # also: stop next prev live guide reloadChannels open close toggle
```

Live TV is always the whole tower. A recording is one station; one with no video or audio ID records the whole tower once, and the next recording is just that station. Guide: a grid of channels by half hour, search lights matches in it (titles and descriptions); a Shows tab lists one row per show. Watch / Record / Record series (`yagi series`). The record timer (`record due`, every minute) starts queued shows, joins back-to-back episodes into one run, and launches `record finish` to split runs and mark ads. After HUD lua: Close TV and retune.

## Keys

Panel (Super+Shift+T): j/k move, Enter picks, Esc closes, `g` Guide, `v` Recordings. Guide: arrows move, Enter opens the card, `/` search, `s` Grid or Shows, `r` Record, `a` Record series. Recordings: ←/→ Recorded or Scheduled, `x` twice deletes, Shift+K locks. Picking a channel or recording focuses the TV window (`yagi focus`).

TV window:

Space pause / play still behind · `l` live · ←/→ skip 10s · ↑/↓ 1 minute · PgUp/PgDn next/last ad break (games never auto-skip) · inside the last 10s, → is live · j/k channel · r record · y save the pause · c captions · m / middle-click mute · wheel volume.

## Paths

`~/.config/yagi/` channels, guide, state, optional `station_map.json` · `~/.config/mpv/channels.conf` · plugin `~/.config/omarchy/plugins/richardb.yagi` · IPC `$XDG_RUNTIME_DIR/yagi-mpv.sock`. First run is empty. Cleveland RF names: `markets/cleveland.json`.

## If pause / skip / HUD is wrong

1. This machine’s `mpv --version` / manpage — not a wiki.
2. Probe the socket **before** editing lua: live `path` is `fd://0`; never `dvb://`. Then `pause`, video width, and `current-tracks/video/program-id` against the state's `service_id`. Skip and read the path again. A new path means the window reopened.
3. Slow zap: `hud.log` has the key press, `tv-program` or `tv-blank`, `loadfile`, and "first video frame after restart shown"; `dump.log` has each lock time.
4. lua loads at mpv start. Not fixed until they see it.
5. Do not ship another overlay for a demuxer or path bug. Probe the socket first.
