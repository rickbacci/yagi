# AGENTS.md — Yagi

Plugin `richardb.yagi`, `bar-widget`, QML `plugin/BarWidget.qml`. Hyprland + Quickshell + Python + MPV.

**Must** breaks hardware, security, or data. **For now** is a choice: change it with a reason, said first. Richard's "idea" = For now; "rule" = Must.

## Commands
`python3 -m unittest` (repo root) before commit. `bin/yagi status`. After QML: `omarchy restart shell`.

## Must
1. `$USER` only. No `sudo` / `pkexec`.
2. IPC via `get_runtime_socket()` in `$XDG_RUNTIME_DIR`. Never `/tmp/`.
3. ATSC keeps `+28615` Hz.
4. Never take a tuner that is live, recording, or scanning (`engine/pool.py`). Free the frontend before a dump. Scan dwell ≥ 1.2 s.
5. State JSON: `.tmp`, then `os.replace`.
6. Library `$XDG_VIDEOS_DIR/TV`. Close TV wipes the pause dump. Long-lived children start via `own_scope`.

## For now
- Recording the live tower copies its dump, no second tuner; leaving that tower hands the dump to the recording and live takes the free tuner. Else live prefers tuner 0, work tuner 1.
- PiP plays the pause dump, not `dvb://`, so pause can seek.
- QML uses `Color.*` / `Style.*` / `root.bar.*`; the HUD reads the theme's `colors.toml`.
- Window `yagi`: float, pin, 16:9, bottom-right, `monitor/3`. Super+F unpins, then fullscreen.

## Working style
Talk, then plan, then code. Choices after talking, as plain text. Commit when asked; "do all" = one commit per item. No panels or shell restarts while Richard uses the machine. Done means he saw it.
