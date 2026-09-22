# MEMORY.md

Plugin `richardb.omarchy-tv` (`bar-widget`). QML `plugin/BarWidget.qml`. Timezone America/New_York.

Pause dump stops when it is an hour of air ahead of the playhead. The picture stays paused. `l` jumps to that saved end, about an hour behind the air. Picking the station again starts a fresh dump. Close TV still deletes the file. It is not a library recording. An hour of ordinary live watching does not stop the writer.

A test sidecar serves a temp file and must not run the pause cap on the installed `live.ts`. Reap only a sidecar whose file is under that test’s temp dir. Do not match the timeshift path in process args; that kills the PiP (`--log-file=.../hud.log`).

Bars stay up until the first frame. The middle stays empty. Channel changes are the flyout list. The picture has no Prev or Next.

Guide schedule is the broadcast (ATSC EIT on Tuner 1) only. Hide is by channel number. Favorites match by station name.

Tests: `TMPDIR=/home/richardb/.cache/omarchy/tv-test-tmp`. Do not use `/tmp` for IPC or tests.

Super+W quits the window. The HUD starts detached `sync --reap` (mpv kills a non-detached subprocess on the way out). That child deletes `live.ts` after the window pid is gone and the tune lock is free, and it leaves the dump if a player is up. Close TV still uses stop, which waits, then deletes.

Channel zap waits on the tuner lock (~3.5s on the last dump), then lavf’s 5s `max_analyze_duration` because the new file is still at the live edge. The dump floor is 256 KiB (~0.1s). There is no 10s preroll. 62 channel rows still have a 0:0 PID and lock twice.
