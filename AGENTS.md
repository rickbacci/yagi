# AGENTS.md — Omarchy TV

OTA TV for Omarchy (Hyprland + Quickshell + Python + MPV). Current idea: `DESIGN.md` and `skills/omarchy-tv/SKILL.md`. This file is repo rules only.

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
One task. If they batch asks, name the current task, park the rest on the todo list, finish that task before switching.

Talk first. Recommendation with pluses and minuses second. Numbered plan third. Code after they choose. Do not commit unless asked.

Obey **Hard constraints**. DESIGN / skill / README / HUD are the current idea, not a veto. If the goal needs a path they don’t describe, advise that path, discuss, then proceed after we understand each other. Update them after it works. Do not stop to rewrite docs in order to think.

Read this machine’s mpv / Quickshell / Hyprland / DVB docs, not a remembered wiki.

## Done
They saw it, or the running app did. Green tests and “it’s in the lua” are not done. Clock-only HUD is not skip. If they still cannot see it: measure the prediction, record the miss, stop that theory.
