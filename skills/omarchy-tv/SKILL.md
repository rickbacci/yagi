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
Return-to-live seeks the write head. `j`/`k` flash a channel banner and
tune once after you stop on a station. A committed tune fills the new dump,
then `pip-relaunch` remaps the PiP in a new session (this mpv will not
switch muxes on stdin; HUD `play` must not quit the window itself). If Tuner 1
is recording, that committed tune uses the live tuner (0) and does not
steal the recording. If Tuner 1 is idle, it may lock the next station
while the dump starts. Stacked tunes while a retune is running wait for
the banner choice, not for every key.
Library recordings are keepable files in `~/Videos/TV`.
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

Listed on the MPV HUD (pointer enters the PiP — chords flash a few seconds via `show-text`). Do not paint them on the plugin. Super+K is Hyprland’s cheatsheet, not TV.

- Space — pause live (dump fills) / play from that moment, or pause a file
- j / k / ↓ / ↑ — flash the full channel banner for the next/previous station; the tuner changes after you stop on one. Recording on Tuner 1 is left alone. File playback returns to live when that commit runs.
- ← / → — ±15 s in the dump or a recording. On a recording, last skip retunes live. On the dump, last skip toward live seeks the write head. → while already live flashes a red LIVE badge; it does not fill the bar as a fake skip
- l — seek dump write head, or retune after a recording
- r — start/stop library record (while live dump is running)
- Super+F / Cmd+F — Omarchy fullscreen. The wrapper unpins this PiP first because Hyprland no-ops Super+F on a pinned window. Bare `f` and double-click do not fullscreen. Super+LMB moves the PiP; mpv left-drag is off.
- c — captions
- `m` / middle-click — mute only this TV window (mpv stream mute). Does not mute other apps. Wheel is volume.

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
- Hyprland class `omarchy-tv` matches Omarchy `pip.lua` (float, pin, aspect, corner). Pin is static; Super+F goes through `omarchy-tv fullscreen`.
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

`j` toggling captions was stock mpv (`cycle sub`). The HUD script path was on the command line but its forced bindings were not in `input-bindings`. Windowed mpv stdout was DEVNULL and stderr was an empty `hud.log` (no TTY, no `--log-file`), so lua load errors vanished while we were building. `osd-overlay` at the top of `tv_hud.lua` can abort the whole script on this gpu-next; keys must still register. Overlay ASS for the bottom legend does not paint here — `osd_message` / `show-text` does.

Plain left-drag moving the PiP was mpv `--window-dragging` (default yes). Omarchy move is Super+LMB (`hl.dsp.window.drag()`). Super+F doing nothing was Hyprland pin: pin is a static window-rule effect, and `hl.dsp.window.fullscreen({ mode = "fullscreen" })` stays at fullscreen 0 while pinned (measured: 1067×600 stayed put; after unpin the same dispatcher went fullscreen 2 at 2150×900). `hyprctl eval` with a class regex is not Omarchy Super+F. HUD `f` / double-click were a second fullscreen path; fullscreen is Super+F only. `j` “closing” the window was `omarchy-tv prev` quitting the PiP before the new dump existed. Live surf now keeps the window. Feeding a new mux into the same lavf/cache without reset froze the picture (follow kept stuffing stdin; `keep-open` plus `--cache-pause` sat on underrun). Stopping the dump *before* ATSC lock made every `j` wait the whole dwell with a frozen frame. Next station locks on the free tuner when Tuner 1 is idle, then `loadfile - replace` + follow REOPEN. Stacked `j` during a retune started a second dump and froze. `loadfile - replace` on the follow pipe quit this mpv — do not use it. Reaping leftover dumps by matching `omarchy/tv/timeshift/` in argv also killed the PiP (`--log-file=.../hud.log`). Only match `--stream-dump=`. Retuning on every `j`/`k` froze the picture and cut audio; the banner must move immediately and the tuner waits until you stop on a station. After a Tuner-1 overlap, the live dump kept `timeshift-next.sock`; the next retune bound the new dump to that same socket and `stop_dump` quit the new dump — picture froze, audio gone. Alternate dump IPC sockets. A recording on Tuner 1 means overlap is skipped; the committed tune retunes Tuner 0. White `osd_message` channel names were not the HUD banner — `j`/`k` must preview `surf_preview` through `show_hud`. Holding `j` was mpv key-repeat (four prev steps from one press). A play callback that immediately started a second `omarchy-tv play` paused the follow pipe on top of the first cutover and froze the picture (audio underrun). One commit after keys idle; extra `j`/`k` only move the banner and reset the timer. REOPEN of stdin still left the old picture: lavf listed new MPEG-2 tracks after `tv-retuned` but the VO stayed on the previous mux. `loadfile -` quit this mpv. A named FIFO also failed: mpegts probe saw corrupt packets / no audio or video and mpv exited. Recycle-after-dump still closed the window: HUD `omarchy-tv play` is an mpv child (`detach=no`); after ATSC lock it sent `quit` and died with the PiP, so `launch_file` never ran (hud.log: play WEWSHD at 9.7s, quit at 15.1s, then shutdown `sync`; `player_state` running false; dump leftover on Tuner 1). `pip-relaunch` is a new session that holds the retune lock across quit+launch. Do not unmute on `tv-retuned` — `m` is TV-only mute.

Learn: when the user still cannot see it, the assumption is wrong, not the paint. Probe `path`, `eof-reached`, and `time-pos` before another HUD pass. Write the failed prediction here, not another overlay.

The rewritten invariant: dump TS on Tuner 0, follow that file to a pipe, one windowed MPV on stdin. Channel change remaps that PiP from a new session after the new dump exists. After a behavior change, AGENTS / DESIGN / this skill / README / HUD must match. Guessed constants (15 s skip, overlay `pos`) are not spec.

## What reviewers would cut later

Keep until we prove we do not need them:

- **Docs person:** AGENTS.md is always-on repo rules. Player manuals go in this skill + `DESIGN.md`. Do not duplicate. If two files disagree, that is a bug — stop and align.
- **Platform person:** Pin behavior to `mpv --version` on this box. `dvbin` seekable-ranges lying is why the PiP is file-only. Default VO in 0.41 is `gpu-next`.
- **QA person:** Observe the process. One IPC probe beats five HUD redesigns.
- **API person:** Window path is `-` (follow pipe) or a library file. Dump process holds DVB. Follow process waits at EOF. Do not freeze guessed skip/cache numbers into invariants.
- **Product person:** Keys live on the HUD (mouse over the player). Not the plugin. Not Super+K. Two sessions (watch + record) are two flyout cards. If a written guideline prevents the product, raise it — do not work around it in silence.
