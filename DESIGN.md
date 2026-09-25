# Omarchy TV — Design

Thin local appliance: Quickshell chrome, Python for DVB/scan/EPG/DVR/timeshift, MPV for decode and HUD. No MySQL, no root, no second frontend.

```
Quickshell plugin (BarWidget.qml KeyboardPanel)
        │ atomic JSON + IpcHandler
Python engine (tuner · scan · guide · DVR · timeshift)
        │
   /dev/dvb          MPV PiP + tv_hud.lua
```

No `Panel.qml`. The flyout is `BarWidget.qml`’s `KeyboardPanel`. The widget root exposes `opened` / `open()` / `close()` so `omarchy-shell shell toggle richardb.omarchy-tv` can summon it the same way as audio and bluetooth.

## Decisions

**Tuners.** Hauppauge dualHD is two adapters, shared as one pool (`engine/pool.py`). Live TV, recordings, scans, and Guide updates each take a free tuner; live prefers 0, the rest prefer 1, so with nothing else on the old split holds. Nothing takes a tuner that is live, recording, or scanning. A Guide update gives way: to live TV at once, to a recording between towers. Two recordings can run while the TV is closed. If both tuners are recording and you pick a channel, the flyout asks which recording to stop. A channel change keeps its tuner, then `loadfile` in the same PiP. Close DVB frontends before a new dump (`EBUSY`).

**ATSC.** Every frequency is nominal `+28615` Hz (A/53 pilot). Scan dwell ≥ 1.2 s. Do not round tables to `000000`.

**Library vs pause-live.** `r` writes keepable files to `$XDG_VIDEOS_DIR/TV` (Recordings, on a free tuner). Space pauses the throwaway `live.ts` under `$XDG_CACHE_HOME/omarchy/tv/timeshift` (the live dump). Save (`y`) copies the paused stretch into Recordings. They can run together.

**PiP is never `dvb://`.** The live tuner dumps growing `live.ts`. A follower copies it onto a fifo. The window reads that once as `fd://0`. Channel change is the only `loadfile`. Skip and live SEEK the follower. Close TV wipes the dump. End of a library file retunes the last live station. One window. Until the first frame, the window may be black: the top bar and the bottom line stay up, and the middle stays empty. After a frame, those bars hide on their own. HUD `play` must not quit the window.

**State.** JSON via `.tmp` + `os.replace`. `player_state.json` is now-playing. `sync` must not wipe a dump while a retune lock is held.

**Flyout.** What’s on is one line: channel, show, then Close on the right. A recording is the same line, with Stop. A Guide update uses that same second line: Updating the Guide, with no Stop. It leaves when the update finishes. A scan keeps its progress card. The show name shortens if the row runs out of room. The channel list sits under that, behind Show / Hide. It opens on Favorites. All is every station not hidden, with Hide, and Hidden holds the stations you set aside. Rescan sits at the end of that row. The list stays while something records; clicking a station watches it. A tune that never becomes a picture leaves the station already on, and the watch row says the new station did not come up. While the try runs, that row shows the signal in dB. Clicking that row, aside from Close, tunes the station named there again. The channel flyout and Recordings stay inside the screen, and only as wide as one line needs. The Guide button turns the flyout into the Guide: search, the time-of-day tabs, one row per show, and the shows waiting to record. The channel list hides while it is open, and the flyout widens. Closed, it is the tuner rows at the narrow width. One line outside the strip only when a show is waiting. Each station in the list is one line: number, name, show, and a star. Only the station you are watching (accent) or recording (urgent) gets a thin edge on the left. Colors come from the Omarchy theme; the HUD reads the same theme file. Changing the channel already on stays on the picture.

**Guide.** The schedule is only what each station sends in the broadcast (ATSC EIT and ETT). No website and no paid listings. Titles, times, and a description when one is sent. What they send usually covers about five hours; some send nothing. The record timer reads it on a free tuner every three hours, one tower at a time, and again after a scan. A recording that comes due takes that tuner back between towers; live TV takes it at once. Any update shows in the flyout as "Updating the Guide · tower N of M" (`guide_status.json`). Each read adds to a four-week history (`guide_history.json`). The guide is split by job. Watching: each channel row shows the show on now, a progress bar, and what is next; the HUD uses the same broadcast times. Recording: the Guide button opens one row per show, channel, and time of day (Day, Prime 8–11 PM, Late 11 PM–2 AM, Overnight 2–6 AM), with its pattern (Nightly, Weeknights, Wednesdays, Marathon) from the history, and its next airing. Each row has Watch when it is on, Record for the next airing, and Record all. Paid Programming and To Be Announced are left out. Record all saves a rule (`record_rules.json`) for the show on that channel at any hour; the timer queues each listed airing once, skips an episode whose description matches one already recorded, and ignores a blurb every episode shares. Airings back to back on one channel record as one run on one tuner, then split into one file per episode. Finished recordings get their ad breaks marked (Comskip if installed, else ffmpeg black and silence); the HUD jumps each break once. A show can keep only its newest 10 or 30. The size limit deletes series episodes first, and never a locked recording or the newest one. Search also reads descriptions, so a team name finds the game; games record 45 minutes past their slot. Search and the shows waiting to record (`schedule.json`) stay in the strip. Recordings stays the library of files already saved. A missing `guide.json` is empty until the first read, not a canned lineup.

**Size limit.** `pref library-max` is `auto` (100 GB, less on a small or full disk), a GB number, or `off`. A show's keep-newest limit goes first. Over the size limit, the oldest Record all episodes go before anything recorded by hand. A locked recording, one still recording, and the newest one are never deleted. The pause dump is not in that budget. It stops when it is an hour of air ahead of the playhead. The picture stays paused, and Close TV still deletes the file.

**Picture IDs.** A station whose lineup still has no video or audio ID is dumped as the whole channel group once. Those IDs are saved, and the next dump of that station is just that station. You do not walk the lineup to fill them in.

Repo rules: `AGENTS.md`. Agent how-to: `skills/omarchy-tv/SKILL.md`. Install: `README.md`. Leftover: `WHATS_LEFT.md`. Hardware: `HARDWARE_AND_TROUBLESHOOTING.md`.
