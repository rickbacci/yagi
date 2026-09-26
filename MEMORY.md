# MEMORY.md

Plugin `richardb.omarchy-tv` (`bar-widget`). QML `plugin/BarWidget.qml`. Timezone America/New_York.

Pause dump stops an hour of air ahead of the playhead. `l` jumps to that end. Picking the station again starts a fresh dump. Close TV deletes it. Ordinary live watching does not stop the writer.

Do not match the timeshift path in process args; that kills the PiP.

Bars stay up until the first frame. Live dump is always the whole tower. Same-tower zap = HUD picks tracks by program-id (`tv-program`), then drop-buffers (station clocks differ ~25 s), no retune; new files pick in `on_preloaded`. mpv 0.41 has no `program` property. Other tower: `engine/tower_dump.py` holds the tuner open; `tune <Hz>` truncates live.ts, ~3 s lock, black until the frame. Reap matches its argv, never text. j and k change channel. Left and right skip.

Guide is broadcast EIT only, every 3h on a free tuner; it yields to live at once. Listings reach ~5h. Network names are a hand-typed Cleveland map, not broadcast. Rescan rewrites the lineup; each Guide read fixes PIDs from the PMT. All = not hidden.

Tests: `python3 -m unittest` from the root; `tests/__init__.py` sandboxes XDG. Never `/tmp`.

Richard: ADD. Dry sarcasm, short. One task in the first sentence. Park the rest on the todo list. Before any install, say what, from where, and how trusted.

Super+W quits. The HUD starts detached `sync --reap`; it deletes `live.ts` once the window and tune lock are gone.

Recordings: sidecar JSON, active once growing, stop under 8 GB free. The oneshot timer (`record due` each minute) kills its children, so recorders, finish, and its Guide update use `own_scope`. The timer runs the last commit from `~/.local/share/omarchy-tv/current` (`githooks/`, `core.hooksPath`), never the working tree. Record all = title + channel, any hour. Back-to-back airings are one run; `record finish` splits them and marks ads. HUD skips each break once; library seeks: `byte_rate` to bytes, then `start=<pct>%` (`#N` is a chapter). Cap: keep_last, then series first; never locked or newest. Save (y) copies the pause. Live picture is one fd://0 reader on the follow fifo.
