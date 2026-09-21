# Omarchy TV — Design

Thin local appliance: Quickshell chrome, Python for DVB/scan/EPG/DVR/timeshift, MPV for decode and HUD. No MySQL, no root, no second frontend.

```
Quickshell plugin (BarWidget.qml KeyboardPanel)
        │ atomic JSON + IpcHandler
Python engine (tuner · scan · guide · DVR · timeshift)
        │
   /dev/dvb          MPV PiP + tv_hud.lua
```

No `Panel.qml`. The flyout is `BarWidget.qml`’s `KeyboardPanel`.

## Decisions

**Tuners.** Hauppauge dualHD is two adapters. Tuner 0: live dump + pause buffer. Tuner 1: scan, EPG, library record. A recording holds Tuner 1; live `j`/`k` then retune Tuner 0. Close DVB frontends before a new dump (`EBUSY`).

**ATSC.** Every frequency is nominal `+28615` Hz (A/53 pilot). Scan dwell ≥ 1.2 s. Do not round tables to `000000`.

**Library vs pause-live.** `r` writes keepable files to `$XDG_VIDEOS_DIR/TV` (Recordings, Tuner 1). Space writes throwaway `live.ts` under `$XDG_CACHE_HOME/omarchy/tv/timeshift` (Tuner 0 dump). Pause files are never in Recordings. They can run together.

**PiP is never `dvb://`.** Tuner 0 dumps growing `live.ts`. A loopback HTTP sidecar serves it (`from=` playhead, wait at EOF). That process outlives `omarchy-tv play` — an in-process server dies when play returns and the PiP flashes then exits. Live and skip are `loadfile` of that URL in the same window. Channel change: new dump, then `pip-relaunch`. Close TV wipes the dump and the sidecar. End of a library file retunes the last live station. One window; no idle/black PiP; HUD `play` must not quit it. A pipe is not seekable — do not SEEK a follow feeder.

**State.** JSON via `.tmp` + `os.replace`. `player_state.json` is now-playing. `sync` must not wipe a dump while a retune lock is held.

**Flyout.** Channel list hides while watching. Guide is a 6:00 PM–11:00 PM `KeyboardPanel` grid (template, not live PSIP).

**Library cap.** Oldest finished files until `pref library-max` fits (`auto` ~20 GB, a GB number, or `off`). Timeshift cache is not in that budget.

Skip seconds and overlay pixels are preferences, not spec. Repo rules: `AGENTS.md`. Agent how-to: `skills/omarchy-tv/SKILL.md`. Install / Hyprland snippet: `README.md`.
