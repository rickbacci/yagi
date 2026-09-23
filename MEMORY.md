# MEMORY.md

Plugin `richardb.omarchy-tv` (`bar-widget`). QML `plugin/BarWidget.qml`. Timezone America/New_York.

Pause dump stops when it is an hour of air ahead of the playhead. The picture stays paused. `l` jumps to that saved end, about an hour behind the air. Picking the station again starts a fresh dump. Close TV still deletes the file. It is not a library recording. An hour of ordinary live watching does not stop the writer.

A test sidecar must not run the pause cap on the installed `live.ts`. Reap only a sidecar whose file is under that test’s temp dir. Do not match the timeshift path in process args; that kills the PiP.

Bars stay up until the first frame. The middle stays empty. A channel click keeps the window and blacks the picture until the new frame. This mpv reopens the tuner and locks again for every station, including a subchannel. The banner re-reads the live station while the picture is up. j and k change channel. Left and right stay skip.

Guide is Tuner 1 EIT only. A rescan rewrites the lineup. This scanner copies some subchannel video ids (43.1 copies 19.1, 3.3 copies 3.1). Favorites and hidden stay. List stays open on Favorites. All is every station.

Tests: `TMPDIR=/home/richardb/.cache/omarchy/tv-test-tmp`. Do not use `/tmp` for IPC or tests.

Richard: ADD. Dry sarcasm, short. One task in the first sentence. Park the rest on the todo list. Do not let a side concern become the task.

Super+W quits the window. The HUD starts detached `sync --reap`. That child deletes `live.ts` after the window pid is gone and the tune lock is free, and it leaves the dump if a player is up. Close TV still uses stop, which waits, then deletes.

Channel zap reuses the dump and locks again. A 0:0 or copied video id plays the whole tower by service id. A missed tune lock fails. Channel rows use the airing date. Library dumps use that full-mux rule and a sidecar. Active only after the file grows; a failed partial stays. Under 8 GB free, the writer stops. HUD r is the station on screen. A user timer runs record due each minute. Keep copies that pause into the library. The pause-reader canvas is the open work. Update it as those todos move unasked.
