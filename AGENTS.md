# AGENTS.md — Omarchy TV Development Guide

Modern Over-The-Air (OTA) digital TV suite for Omarchy (Hyprland + Quickshell + Python + MPV).

## Quick Commands
- **Run Tests**: `python3 -m unittest discover tests` (must pass 100% before committing)
- **CLI Diagnostics**: `bin/omarchy-tv status`
- **Reload Shell Widget**: `omarchy restart shell`
- **Hyprland Rules Check**: `hyprctl reload && hyprctl configerrors`

## Architectural Invariants
1. **Zero Privilege**: Run 100% unprivileged (`$USER`). NEVER execute `sudo` or `pkexec`. Tuner access uses systemd active seat ACLs (`user:$USER:rw-`).
2. **Secure Sockets**: Always resolve IPC sockets inside `$XDG_RUNTIME_DIR` (mode `0700`) via `engine.paths.get_runtime_socket()`. Never hardcode `/tmp/`.
3. **ATSC Pilot Offset**: All ATSC frequencies must maintain the exact `+28615` Hz pilot carrier offset (ATSC A/53 specification). Never use nominal 000000 Hz centers.
4. **Multi-Tuner Lease**: Use `TunerManager.get_available_tuner()`. Tuner 0 is preferred for live playback; Tuner 1 for background scans, EPG, and library record. A recording holds Tuner 1 — do not steal it to preview the next live station. If Tuner 1 is idle, a committed channel change may lock the next station there while the PiP still plays Tuner 0.
5. **Atomic File Writes**: State files (`channels.json`, `scan_status.json`, `player_state.json`, DVR indexes) must be written to `.tmp` and committed via POSIX `os.replace`.
6. **Quickshell Theming**: Never hardcode colors or dimensions. Use `Color.accent`, `root.bar.barForeground`, `root.bar.fontFamily`, `Style.space()`, and `Style.font.*` tokens (`display`, `title`, `body`, `caption`). Do not paint keybinding chords on the plugin; those belong on the MPV HUD (`player/scripts/tv_hud.lua`).
7. **Hyprland Rules**: Match Omarchy PiP (`/usr/share/omarchy/default/hypr/apps/pip.lua`): float, pin, `keep_aspect_ratio`, corner `move` with `window_w`. Pin is a static Hyprland effect and Super+F no-ops while pinned — `omarchy-tv fullscreen` unpins first, then the same dispatcher as tiling.lua. Fullscreen is Super+F only (no HUD `f`). Do not let mpv `--window-dragging` move the PiP; Omarchy move is Super+LMB.
8. **DVB Hand-Off (EBUSY Prevention)**: Background routines MUST release `/dev/dvb/adapter*/frontend0` file descriptors before invoking MPV playback to prevent hardware lock contention.
9. **Demodulator Dwell Window**: ATSC 8VSB carrier recovery requires a minimum 1.2s dwell timeout per frequency. Never reduce scan timeout below 1.2s.
10. **DVR vs timeshift**: Library recordings go to `$XDG_VIDEOS_DIR/TV` (default `~/Videos/TV`) and appear in the Recordings view. Pause-live is a throwaway growing MPEG-TS dump on Tuner 0 (`$XDG_CACHE_HOME/omarchy/tv/timeshift/live.ts`). The PiP reads a follow pipe of that file (no `dvbin` in the window) — one window, never an idle/black PiP. It is not a library recording. Channel change replaces that dump, then `pip-relaunch` remaps the PiP in a new session so HUD `play` is not killed with the old window. Tuner 1 locks the next station when free. Close TV wipes dump and window. Do not treat skip length, overlay pixels, or cache minutes as spec.
11. **Return to live**: Delayed live becomes live by seeking the dump’s write head. From a library file, Close TV, or `omarchy-tv live` after a file: retune the last live station (new dump + play the new file) and wipe the old pause cache. Do not play `dvb://` in the window to “fix” pause.

## Working Style
Talk first. Questions second, each with a recommendation. Code third — after they have an answer, or they have already chosen.
When the user batches several requests in one message, reply with a numbered plan in implementation order, then execute in that order.
Do not commit unless the user explicitly asks. Tests must be 100% green before any commit.
Read the **installed** docs for the component you are changing (this machine’s mpv, Quickshell, Hyprland, DVB). Not a remembered API, not a different version’s wiki.
If a guideline in this file, `DESIGN.md`, or `skills/omarchy-tv/SKILL.md` would block what the user asked for, **stop and say so**. Either change the guideline with them, or follow it. Do not silently implement a third path that fights the docs.
Do not hardcode guessed MVP numbers into architecture. ATSC `+28615` Hz and ≥1.2 s scan dwell are spec. Skip seconds, cache minutes, LIVE pixel positions, and “15 s is standard” are preferences until this hardware and this mpv prove them.
Keep AGENTS, DESIGN, the skill, README, and HUD copy saying the same thing. One behavior change updates all of them. If two docs disagree, align them before more code.
Do not tell the user a player, HUD, or plugin bug is fixed until the running app has done it, or they have. Green tests and “it’s in the lua” are not that.
If they still cannot see it, do not ship another variant of the same theory. Ask why you thought it would work, measure that prediction on the running process, and record the failed assumption in the skill that owns the domain.
TV product behavior belongs in `skills/omarchy-tv/SKILL.md` and `DESIGN.md`. Keep this file to repo rules, not a second player manual.
