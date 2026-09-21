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
4. **Multi-Tuner Lease**: Use `TunerManager.get_available_tuner()`. Tuner 0 is preferred for live playback; Tuner 1 for background scans, EPG sync, and recording.
5. **Atomic File Writes**: State files (`channels.json`, `scan_status.json`, `player_state.json`, DVR indexes) must be written to `.tmp` and committed via POSIX `os.replace`.
6. **Quickshell Theming**: Never hardcode colors or dimensions. Use `Color.accent`, `root.bar.barForeground`, `root.bar.fontFamily`, `Style.space()`, and `Style.font.*` tokens (`display`, `title`, `body`, `caption`). Do not paint keybinding chords on the plugin; those belong on the MPV HUD (`player/scripts/tv_hud.lua`).
7. **Hyprland Rules**: Use `o.window("omarchy-tv", { keep_aspect_ratio = true, pin = true, ... })` in `~/.config/hypr/hyprland.lua`.
8. **DVB Hand-Off (EBUSY Prevention)**: Background routines MUST release `/dev/dvb/adapter*/frontend0` file descriptors before invoking MPV playback to prevent hardware lock contention.
9. **Demodulator Dwell Window**: ATSC 8VSB carrier recovery requires a minimum 1.2s dwell timeout per frequency. Never reduce scan timeout below 1.2s.
10. **DVR vs timeshift**: Library recordings go to `$XDG_VIDEOS_DIR/TV` (default `~/Videos/TV`) and appear in the Recordings view. Pause-live dumps go to `$XDG_CACHE_HOME/omarchy/tv/timeshift` (15 minutes, throwaway). Never index timeshift files in the library. Recording/timeshift playback is file-only MPV (no `dvbin`).
11. **Return to live**: EOF, seek-to-end, Close TV, or `omarchy-tv live` must retune the last live station and delete the timeshift buffer.

## Working Style
When the user batches several requests in one message, reply with a numbered plan in implementation order, then execute in that order.
Do not commit unless the user explicitly asks. Tests must be 100% green before any commit.
