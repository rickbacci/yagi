# MEMORY.md

Plugin `richardb.omarchy-tv` (`bar-widget`). QML `plugin/BarWidget.qml`. Timezone America/New_York.

Pause dump stops when it is an hour of air ahead of the playhead. The picture stays paused. `l` jumps to that saved end, about an hour behind the air. Picking the station again starts a fresh dump. Close TV still deletes the file. It is not a library recording. An hour of ordinary live watching does not stop the writer.

A test sidecar serves a temp file and must not run the pause cap on the installed `live.ts`. Reap only a sidecar whose file is under that test’s temp dir. Do not match the timeshift path in process args; that kills the PiP (`--log-file=.../hud.log`).

Bars stay up until the first frame. The middle stays empty. A channel click keeps the window and blacks the picture until the new frame. This mpv reopens the tuner and locks again for every station, including a subchannel. The banner re-reads the live station while the picture is up. The picture has no Prev or Next.

Guide is Tuner 1 EIT only. A rescan rewrites the lineup. This scanner copies some subchannel video ids (43.1 copies 19.1, 3.3 copies 3.1). Favorites and hidden stay. List stays open on Favorites. All is every station.

Tests: `TMPDIR=/home/richardb/.cache/omarchy/tv-test-tmp`. Do not use `/tmp` for IPC or tests.

Richard: ADD. Dry sarcasm, short. One task in the first sentence. Park the rest on the todo list. Do not let a side concern become the task.

Super+W quits the window. The HUD starts detached `sync --reap` (mpv kills a non-detached subprocess on the way out). That child deletes `live.ts` after the window pid is gone and the tune lock is free, and it leaves the dump if a player is up. Close TV still uses stop, which waits, then deletes.

Channel zap reuses the running dump. Every station locks again inside that mpv. A 0:0 or copied video id plays the whole tower by service id. Learning stays off the zap. The old live.ts is deleted off the zap. Picking the same station again still starts a fresh dump. A fresh picture opens at the start of the file, probe 2s. A 0.4s probe found no streams and quit. The 5s probe at the live edge left 3.2 black for 48s.
