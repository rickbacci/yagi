---
name: omarchy-tv
description: >
  Control OTA ATSC TV on Omarchy (bar plugin, PiP, Hauppauge dual tuner).
  Use when asked to watch live TV, scan, open the guide, record, pause live,
  play a recording, or inspect tuners. Triggers: TV, live TV, OTA, ATSC,
  tuner, scan, DVR, timeshift, pause live, EPG, HUD, recordings.
---

# Omarchy TV

Project `~/Projects/personal/omarchy-tv`. CLI `omarchy-tv` (`PATH` or `bin/`). Product: `DESIGN.md`. Repo rules: `AGENTS.md`.

**Live:** Tuner 0 dumps `~/.cache/omarchy/tv/timeshift/live.ts`; a follow process copies it to PiP stdin (`path` is `-` / `fd://`). This mpv `keep-open` freezes on the growing file — that is why live is a pipe.
**Delayed:** `loadfile` that dump at `start=#` (same byte seek as a recording). Do not SEEK the follow feeder; a pipe is not seekable.
**Live again:** `omarchy-tv live` / `pip-relaunch` remaps the follow pipe. Library files live in `~/Videos/TV` and are not the pause dump. Never `dvb://` in the PiP. Never `drop-buffers`.

Tuner 0 live dump; Tuner 1 scan / record. A recording holds Tuner 1. `j`/`k` move the banner immediately; tune once after keys idle. Channel change fills a new dump, then `pip-relaunch` (HUD `play` must not quit this mpv). Close TV wipes the dump. One `omarchy-tv` window.

## CLI

```bash
omarchy-tv play "8.1 FOX" | next | prev | stop | sync | pause | live | seek 10
omarchy-tv record start "8.1 FOX" 1h | stop | list | play <file> | delete <file>
omarchy-tv list | guide | status | scan | scan --full
omarchy-tv favorite toggle "8.1 FOX"
omarchy-tv pref filter all|favorites | pref translators off | pref library-max auto|20|50|off
omarchy-shell shell broadcast richardb.omarchy-tv play "8.1 FOX"   # also: stop next prev live guide reloadChannels
```

`record` is a keepable file. `pause` is throwaway `live.ts`. After QML: `omarchy restart shell`. After HUD lua: Close TV and retune.

## HUD (PiP only — not the plugin, not Super+K)

Space pause (dump fills) / play still behind · `l` live · j/k or ↓/↑ banner then tune · ←/→ skip in dump file or recording (10s, 5s near live; last hop is live / retune) · r record · Super+F fullscreen (unpins first) · Super+LMB move · c captions · m / middle-click mute this window · wheel volume.

## Paths

`~/.config/omarchy/tv/` channels, guide, state · `~/.config/mpv/channels.conf` · plugin `~/.config/omarchy/plugins/richardb.omarchy-tv` · recordings `~/Videos/TV` · dump `~/.cache/omarchy/tv/timeshift/live.ts` · IPC `$XDG_RUNTIME_DIR/omarchy-tv-mpv.sock`

## If pause / skip / HUD is wrong

1. This machine’s `mpv --version` / manpage — not a wiki.
2. Probe the socket **before** editing lua: live `path` is `-`/`fd://`; delayed is `live.ts`; never `dvb://`. Then `pause`, `time-pos`. Skip and read them again. If only the HUD clock moved, the decoder did not seek.
3. lua loads at mpv start. Not fixed until they see it (or have).
4. Failed predictions: [failures.md](failures.md). Do not ship another overlay for a demuxer/path bug.
