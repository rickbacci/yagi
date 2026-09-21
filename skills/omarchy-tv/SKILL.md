---
name: omarchy-tv
description: >
  Control Over-The-Air (OTA) television on Omarchy using the Omarchy TV suite
  and Hauppauge dual-tuner hardware. Use when asked to watch live TV, scan
  channels, open the guide, record a station, pause live TV, play a recording,
  or inspect tuners and signal. Triggers: TV, watch TV, live TV, OTA, antenna,
  broadcast, tuner, ATSC, channels, scan channels, DVR, record, timeshift,
  pause live, guide, EPG, recordings, LIVE badge, HUD, timeshift.
---

# Omarchy TV Skill

Control live ATSC television on Omarchy (Hyprland + Quickshell + MPV). Project:
`~/Projects/personal/omarchy-tv`. CLI: `~/Projects/personal/omarchy-tv/bin/omarchy-tv`
(or `omarchy-tv` on `PATH`).

## What the app is

A bar plugin plus a floating PiP player. Scan OTA, dump live TS on Tuner 0,
record on Tuner 1, play files from `~/Videos/TV`.

Live watch is **three processes**: a headless `--stream-dump` of `dvb://`
into `~/.cache/omarchy/tv/timeshift/live.ts`, a follow copy of that file
to stdout (waits at EOF instead of closing), and one windowed MPV that
reads the pipe (no `dvbin` in the window). Pause stops the reader; the
dump keeps writing. Skip is a byte-offset SEEK on the follow socket.
Return-to-live seeks the write head. Channel change wipes the dump and
opens one new window. Library recordings are keepable files in `~/Videos/TV`.
Do not spawn a second `omarchy-tv` window. Do not open an idle/black PiP
while the dump starts. mpv 0.41 `--keep-open` does not follow a growing
`live.ts`; that is why the window reads the follow pipe.

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

### Pause live and return to the write head

```bash
omarchy-tv pause         # freeze the picture; dump keeps filling
omarchy-tv live          # seek dump write head, or retune after a recording
omarchy-tv seek 15       # skip in the live dump or a library file
```

Do not use `record` when the user wants to freeze live and continue later.
`record` writes a keepable file into `~/Videos/TV`. Pause writes throwaway
`live.ts`. Do not call MPV `drop-buffers`. Do not play `dvb://` in the PiP.

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

Listed on the MPV HUD (mouse over the player). Do not paint them on the plugin. Super+K is Hyprland’s cheatsheet, not TV.

- Space — pause live (dump fills) / play from that moment, or pause a file
- j / k / ↓ / ↑ — always previous / next channel (file playback returns to live first)
- ← / → — ±15 s in the dump or a recording. On a recording, last skip retunes live. On the dump, last skip toward live seeks the write head. → while already live flashes a red LIVE badge; it does not fill the bar as a fake skip
- l — seek dump write head, or retune after a recording
- r — start/stop library record (while live dump is running)
- f / double-click — compositor fullscreen
- Wheel / middle-click — volume / mute

## Layout

- Project: `~/Projects/personal/omarchy-tv`
- Channels: `~/.config/omarchy/tv/channels.json`
- MPV table: `~/.config/mpv/channels.conf`
- Plugin: `~/.config/omarchy/plugins/richardb.omarchy-tv`
- Recordings: `~/Videos/TV`
- Timeshift: `~/.cache/omarchy/tv/timeshift/live.ts`

## Invariants

- No sudo / pkexec. Tuner ACLs are the active seat.
- ATSC frequencies keep `+28615` Hz. Never round to `000000`.
- Tuner 0 live dump; Tuner 1 scan / record. PiP is file-only.
- Pause-live is the growing dump file, read through a follow pipe so the
  picture does not freeze at EOF. Seek must move playback on this mpv. If
  `path` is `dvb://`, the window is wrong — stop and fix, do not paint
  overlays. Re-check `mpv --version` before assuming dump+follow still holds.
- Release DVB frontends before a new dump (`EBUSY`).
- IPC sockets via `engine.paths.get_runtime_socket()` in `$XDG_RUNTIME_DIR`.
- Atomic JSON: write `.tmp`, `os.replace`.
- Scan dwell ≥ 1.2 s.
- Plugin: `Color.*` / `Style.*` tokens; no hardcoded key chords.
- Hyprland class `omarchy-tv` is a floated, pinned, aspect-locked PiP.
- Tests: `python3 -m unittest discover tests` must be 100% before commit.
- Do not commit unless the user asked.

## Pause / LIVE / HUD is wrong

1. Read **this machine’s** docs: `mpv --version`, `mpv --list-options`, the mpv manpage for `osd-overlay`, `seek`, `stream-dump`. Same for Quickshell if the flyout is the bug.
2. Probe the running player over `$XDG_RUNTIME_DIR/omarchy-tv-mpv.sock` **before** editing lua: `path` must be `live.ts` (not `dvb://`), then `pause`, `time-pos`. Seek, read `time-pos` again. If it did not move, the dump is not what the window is playing.
3. `tv_hud.lua` loads at MPV start. Close TV and retune after lua edits. `omarchy restart shell` after QML.
4. Do not say LIVE, skip, or the buffer bar is fixed until the picture has done it (or the user has). Grep tests and “the ASS is in the file” do not count.
5. Do not call `drop-buffers`. Do not open `dvb://` in the PiP to “get live back.”

## Why the last theory failed

We treated MPV disk cache on `dvb://` like WinTV: pause, skip, catch live, flash LIVE. That predicted `seek` would move `time-pos`.

What actually happened: `seek` returned success and `time-pos` did not move. Then `loadfile` of the same `dvb://` URL also did nothing. Overlay color/position changes could not fix a demuxer that never restarted.

Then we dumped to `live.ts` and played the file with `--keep-open`. That predicted the window would follow the growing TS. What actually happened: mpv probed ~256 KiB, played about a second, set `eof-reached` true, and sat on a black/frozen frame while `live.ts` kept growing. A second prediction also failed: `launch_idle` (`--force-window=immediate`, no file) plus unlinking the IPC socket while an old PiP PID was still alive opened a **second** black `omarchy-tv` window. The leftover window went black when the new dump stole the tuner.

`--force-window=yes` on the follow pipe also failed: CLI/`player_state` said running while Hyprland had no `omarchy-tv` client until the first decoded frame. The flyout hid the channel list in that gap, so TV looked like it never opened. `--force-window=immediate` on the follow pipe maps one window as soon as MPV starts (not the idle-no-file PiP). A 3s IPC wait also lied: dump lock takes several seconds, then mpv may not bind the socket yet, so `omarchy-tv play` exited 1 while dump/follow/mpv were still starting. The flyout killing that CLI on a second click of the same channel left a tuner-busy dump and no window.

Cmd+W / compositor close of the PiP was the next miss: lua cleared now-playing (list came back) but the dump kept the tuner. Clicking another channel started a new dump; the flyout `sync` timer (every 1.5s while a station name is set) saw no window yet and wiped that dump. Super+W is Close TV for the dump, but not while a retune lock is held.

Learn: when the user still cannot see it, the assumption is wrong, not the paint. Probe `path`, `eof-reached`, and `time-pos` before another HUD pass. Write the failed prediction here, not another overlay.

The rewritten invariant: dump TS on Tuner 0, follow that file to a pipe, one windowed MPV on stdin. That is how the picture keeps moving on this mpv 0.41. After a behavior change, AGENTS / DESIGN / this skill / README / HUD must match. Guessed constants (15 s skip, overlay `pos`) are not spec.

## What reviewers would cut later

Keep until we prove we do not need them:

- **Docs person:** AGENTS.md is always-on repo rules. Player manuals go in this skill + `DESIGN.md`. Do not duplicate. If two files disagree, that is a bug — stop and align.
- **Platform person:** Pin behavior to `mpv --version` on this box. `dvbin` seekable-ranges lying is why the PiP is file-only. Default VO in 0.41 is `gpu-next`.
- **QA person:** Observe the process. One IPC probe beats five HUD redesigns.
- **API person:** Window path is `-` (follow pipe) or a library file. Dump process holds DVB. Follow process waits at EOF. Do not freeze guessed skip/cache numbers into invariants.
- **Product person:** Keys live on the HUD (mouse over the player). Not the plugin. Not Super+K. Two sessions (watch + record) are two flyout cards. If a written guideline prevents the product, raise it — do not work around it in silence.
