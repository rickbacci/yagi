# AGENTS.md — Yagi

Omarchy bar plugin for over-the-air ATSC 1.0. Plugin id `richardb.yagi`, entry `plugin/BarWidget.qml`. Hyprland, Quickshell, Python, and mpv.

## Layout

- `bin/yagi` — CLI
- `engine/` — tuners, scan, guide, DVR, timeshift, tower dump
- `player/` — mpv controller and `scripts/tv_hud.lua`
- `plugin/` — Quickshell bar widget
- `markets/` — example station maps (`cleveland.json`)
- `tests/` — unittest suite
- `DESIGN.md` — why the play path works this way
- `HARDWARE_AND_TROUBLESHOOTING.md` — tuners and RF

## Commands

From the repo root, before a commit:

```bash
python3 -m unittest
bin/yagi status
```

Tests sandbox XDG (`tests/__init__.py`) and never put sockets in `/tmp`. After a QML change, `omarchy restart shell`.

## Do

- Run as `$USER`. No `sudo` or `pkexec`.
- Open IPC with `get_runtime_socket()` under `$XDG_RUNTIME_DIR`.
- Keep the ATSC `+28615` Hz pilot. Do not round frequencies to `000000`.
- Leave a tuner that is live, recording, or scanning (`engine/pool.py`). Free the frontend before a dump. Scan dwell is at least 1.2 s.
- Write state JSON to a `.tmp` file, then `os.replace`.
- Put the library in `$XDG_VIDEOS_DIR/TV`. Close TV wipes the pause dump. Start long-lived children with `own_scope`.
- In QML use `Color.*`, `Style.*`, and `root.bar.*`. The HUD reads the theme `colors.toml`.

## Don't

- Do not match the timeshift path in process args. The picture names that file too, and a match kills it.
- Do not open `dvb://` for the picture. The PiP plays the pause dump so pause can seek.
- Recording the tower you are watching copies its dump. Leaving that tower hands the dump to the recording. Otherwise live prefers tuner 0 and other work prefers tuner 1.
- Window class `yagi` is float, pin, 16:9, bottom-right, height `monitor/3`. Super+F unpins, then fullscreen.

Hardware and data rules above stay. Other choices can change when the reason is said first. See `DESIGN.md`.
