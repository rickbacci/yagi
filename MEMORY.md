# MEMORY.md

Plugin `richardb.omarchy-tv` (`bar-widget`). QML `plugin/BarWidget.qml`. Timezone America/New_York.

Pause dump stops an hour of air ahead of the playhead. `l` jumps to that end. Picking the station again starts a fresh dump. Close TV deletes it. Ordinary live watching does not stop the writer.

Do not match the timeshift path in process args; that kills the PiP.

Bars stay up until the first frame. A channel click keeps the window and blacks the picture until the new frame. mpv reopens the tuner and locks again for every station. j and k change channel. Left and right skip.

Guide is broadcast EIT only, every 3h on a free tuner; it yields to live at once. Listings reach ~5h. Network names are a hand-typed Cleveland map, not broadcast. Rescan rewrites the lineup; each Guide read fixes PIDs from the PMT. All = not hidden.

Tests: `TMPDIR=/home/richardb/.cache/omarchy/tv-test-tmp`, `XDG_RUNTIME_DIR` set. Never `/tmp`.

Richard: ADD. Dry sarcasm, short. One task in the first sentence. Park the rest on the todo list. Before any install, say what, from where, and how trusted.

Super+W quits. The HUD starts detached `sync --reap`; it deletes `live.ts` once the window and tune lock are gone.

Channel zap reuses the dump. A 0:0 or copied video id plays the whole tower by service id. Recordings: sidecar JSON, full-mux rule, active once growing, stop under 8 GB free. Recorders run via `own_scope` (systemd scope); the oneshot record timer kills its children. Timer runs `record due` each minute. Record all = title + channel, any hour. Back-to-back airings record as one run, then `record finish` splits per episode and marks ads (ffmpeg, Comskip if installed). HUD skips each ad break once; library seeks use sidecar `byte_rate`. Cap: per-show keep_last, then series first; never locked or newest. Save (y) copies the pause into the library. Live picture is one fd://0 reader on the follow fifo.
