# AGENTS.md — Omarchy TV

Plugin `richardb.omarchy-tv`, kind `bar-widget`, QML `plugin/BarWidget.qml`. Hyprland + Quickshell + Python + MPV. Rules only. Idea docs are not a veto. Overlay and flyout are.

## Commands
`python3 -m unittest discover tests` before commit. `bin/omarchy-tv status`. After QML: `omarchy restart shell`. `hyprctl reload && hyprctl configerrors`.

## Hard constraints
1. `$USER` only. No `sudo` / `pkexec`.
2. IPC: `engine.paths.get_runtime_socket()` in `$XDG_RUNTIME_DIR` (0700). Never `/tmp/`.
3. ATSC keeps `+28615` Hz. Never `000000`.
4. Tuner 0 live; Tuner 1 scan, EPG, record. Do not steal Tuner 1 while recording. Channel change dumps Tuner 0, then `loadfile` in the same PiP.
5. State JSON: `.tmp`, then `os.replace`.
6. QML: `Color.*` / `Style.*` / `root.bar.*` only. HUD owns key chords.
7. Class `omarchy-tv`: float, pin, 16:9, bottom-right, height `monitor/3`. Like `pip.lua`, not tag `pip` or 600×338. Super+F unpins, then fullscreen. No HUD `f`. Move is Super+LMB.
8. Free the frontend before a dump (`EBUSY`). Scan dwell ≥ 1.2 s.
9. Library `$XDG_VIDEOS_DIR/TV`. Pause dump `$XDG_CACHE_HOME/omarchy/tv/timeshift/`. PiP is never `dvb://`. Close TV wipes the dump and lost sidecars.

## Settled
`tv_hud.lua` and `plugin/BarWidget.qml` are settled. Stop, say why the look must change, and wait. Do not restyle, move, add, or drop a word, color, or bar.

## Working style
One task. Talk, then a plan, then code. Commit only when asked. Done means they saw it.
