# AGENTS.md — Omarchy TV

OTA TV for Omarchy (Hyprland + Quickshell + Python + MPV). Product how-to: `DESIGN.md` and `skills/omarchy-tv/SKILL.md`. This file is repo rules only.

## Commands
- Tests: `python3 -m unittest discover tests` (100% before commit)
- Status: `bin/omarchy-tv status`
- Reload widget: `omarchy restart shell`
- Hyprland: `hyprctl reload && hyprctl configerrors`

## Hard constraints
1. Unprivileged `$USER` only. No `sudo` / `pkexec`. Tuner ACLs are the active seat.
2. IPC sockets via `engine.paths.get_runtime_socket()` in `$XDG_RUNTIME_DIR` (0700). Never `/tmp/`.
3. ATSC frequencies keep `+28615` Hz. Never round to `000000`.
4. Tuner 0 for live dump; Tuner 1 for scan / EPG / library record. A recording holds Tuner 1 — do not steal it. Idle Tuner 1 may lock the next station.
5. State JSON: write `.tmp`, `os.replace`.
6. QML: `Color.*` / `Style.*` / `root.bar.*` tokens. No hardcoded key chords on the plugin (HUD owns those).
7. Hyprland class `omarchy-tv` matches Omarchy `pip.lua` (float, pin, aspect, corner). Pin is static; Super+F is `omarchy-tv fullscreen` (unpin first). No HUD `f`. No mpv `--window-dragging`; move is Super+LMB.
8. Release DVB frontends before a new dump (`EBUSY`).
9. Scan dwell ≥ 1.2 s.
10. Library recordings: `$XDG_VIDEOS_DIR/TV`. Pause-live dump: `$XDG_CACHE_HOME/omarchy/tv/timeshift/`. Not the same tree. PiP is never `dvb://`. Close TV wipes the dump.
11. Skip seconds, overlay pixels, cache minutes are preferences until this hardware and this mpv prove them. Do not freeze them here.

## Working style
Talk first. Questions with a recommendation second. Numbered plan third. Code after they answer or have chosen. Do not commit unless asked.

This file’s constraints are spec/security. Product *how* is a decision with a why — record it in DESIGN + skill + README + HUD, then code. If a written method cannot do what they asked, stop. Say what we need and why. Do not keep iterating that method. Do not let docs forbid a working path. If two docs disagree, align them before more code.

Read this machine’s mpv / Quickshell / Hyprland / DVB docs, not a remembered wiki.

Do not call a player/HUD/plugin bug fixed until the running app has done it, or they have. If they still cannot see it, do not ship another variant of the same theory: measure the prediction, record the miss in the skill that owns the domain.
