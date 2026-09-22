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

**PiP is never `dvb://`.** Tuner 0 dumps growing `live.ts`. A loopback HTTP sidecar serves it (`from=` playhead, wait at EOF). That process outlives `omarchy-tv play` — an in-process server dies when play returns and the PiP flashes then exits. Live and skip are `loadfile` of that URL in the same window. Channel change: new dump, then `pip-relaunch`. Close TV wipes the dump, the sidecar, and any sidecar it lost track of. End of a library file retunes the last live station. One window; no idle/black PiP; HUD `play` must not quit it. A pipe is not seekable — do not SEEK a follow feeder.

**State.** JSON via `.tmp` + `os.replace`. `player_state.json` is now-playing. `sync` must not wipe a dump while a retune lock is held.

**Flyout.** What’s on is one line: channel, show, then Close on the right. A recording is the same line, with Stop. A Guide update uses that same second line: Updating the Guide, with no Stop. It leaves when the update finishes. A scan keeps its progress card. The show name shortens if the row runs out of room. The channel list sits under that, behind Show / Hide. It opens on favorites. Favs and Watchable are for watching. All is that same list with Hide, and Hidden holds the stations you set aside. It is open when nothing is on, closed when a tuner is free, and gone when both tuners are busy. Watching holds tuner 0. Recording, a Guide update, or a scan holds tuner 1. The list watches on a free tuner 0, and records when only tuner 1 is free. That click records the show on now, for the time it has left. A tune that never becomes a picture leaves the station already on, and the watch row says the new station did not come up. While the try runs, that row shows the signal in dB. Clicking that row, aside from Close, tunes the station named there again. The channel flyout and Recordings stay inside the screen, and only as wide as one line needs. The Guide button opens a strip: search, then one row per station with the name once and three hours of titles across, Earlier and Later, and the shows waiting to record. The flyout widens while that strip is open. Closed, it is the tuner rows at the narrow width. One line outside the strip only when a show is waiting. Each station in the list is one line: number, name, show, and a star. A thin network-color edge sits on the left. Changing the channel already on stays on the picture.

**Guide.** The schedule is only what each station sends in the broadcast (ATSC EIT). No website and no paid listings. Titles and start and end times only. `omarchy-tv guide refresh` reads that on Tuner 1 and writes `guide.json`. The Guide button opens a strip in the flyout: search, one row per station, three hours of those titles across, Earlier and Later, and the shows waiting to record (`schedule.json`). The flyout widens while that strip is open. A show that is not on yet waits there until its start, then records on a free tuner. Recordings stays the library of files already saved. Stations must send a name, not a show list; some send none. What they send usually covers tonight into early morning, not next week. Each refresh keeps about 10 days of those airings. After the same show turns up on the same channel and clock in a second week, a search can say which day and time it usually airs. A recording holds Tuner 1 — refresh leaves the saved guide alone. A missing `guide.json` is a canned evening lineup until the first refresh, not the air.

**Library cap.** Oldest finished files until `pref library-max` fits (`auto` ~20 GB, a GB number, or `off`). The pause dump is not in that budget. It grows until Close TV. That is the open piece: `WHATS_LEFT.md`.

**Picture IDs.** A station whose lineup still has no video or audio ID is dumped as the whole channel group once. Those IDs are saved, and the next dump of that station is just that station. You do not walk the lineup to fill them in.

The picture overlay and the flyout are settled. Repo rules: `AGENTS.md`. Agent how-to: `skills/omarchy-tv/SKILL.md`. Install / Hyprland snippet: `README.md`. Hardware: `HARDWARE_AND_TROUBLESHOOTING.md`.
