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

**Play path:** Tuner 0 dumps `live.ts`. A sidecar on `127.0.0.1` serves `http://127.0.0.1:…/live.ts?from=`. Playing the file directly hits `keep-open` EOF. Skip and live are `loadfile` of that URL at a new `from=` in the same window. Do not SEEK a pipe. Never `drop-buffers`. HUD `play` must not quit this mpv. One window. Reap a lost sidecar by module `engine.timeshift_http`, not by the timeshift path.

## CLI

```bash
omarchy-tv play "8.1 FOX" | next | prev | stop | sync | pause | live | seek 10
omarchy-tv record start "8.1 FOX" 1h | stop | list | play <file> | delete <file>
omarchy-tv list | guide | guide refresh | guide search Browns | status | scan | scan --full
omarchy-tv favorite toggle "8.1 FOX"
omarchy-tv pref filter favorites|watchable|all|hidden | pref library-max auto|20|50|off
omarchy-tv hidden list | hidden hide 19.1 | hidden show 19.1
omarchy-shell shell broadcast richardb.omarchy-tv play "8.1 FOX"   # also: stop next prev live guide reloadChannels open close toggle
```

A station with no video or audio ID is dumped as the whole channel group once; the next dump is just that station. Guide strip: search, one row per station, three hours, Earlier and Later, `record later` / `record due`. After HUD lua: Close TV and retune.

## Keys

Space pause / play still behind · `l` live · ←/→ skip (10s, 5s near live; last hop is live) · r record · c captions · m / middle-click mute · wheel volume.

## Paths

`~/.config/omarchy/tv/` channels, guide, state, optional `station_map.json` · `~/.config/mpv/channels.conf` · plugin `~/.config/omarchy/plugins/richardb.omarchy-tv` · IPC `$XDG_RUNTIME_DIR/omarchy-tv-mpv.sock`. First run is empty. Cleveland RF names: `markets/cleveland.json`.

## If pause / skip / HUD is wrong

1. This machine’s `mpv --version` / manpage — not a wiki.
2. Probe the socket **before** editing lua: live `path` is `http://127.0.0.1:…/live.ts`; never `dvb://`. Then `pause`, `time-pos`. Skip and read them again. If only the HUD clock moved, the decoder did not seek.
3. lua loads at mpv start. Not fixed until they see it.
4. Do not ship another overlay for a demuxer or path bug. Probe the socket first.
