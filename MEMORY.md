# MEMORY.md

Timezone America/New_York.

Pause dump stops an hour of air ahead of the playhead. `l` jumps to that end. Picking the station again starts a fresh dump. Close TV deletes it. Ordinary live watching does not stop the writer.

Do not match the timeshift path in process args; that kills the PiP.

Bars stay up until the first frame. Live dump is always the whole tower. Same-tower zap = HUD picks tracks by program-id (`tv-program`), then drop-buffers (station clocks differ ~25 s), no retune; new files pick in `on_preloaded`. mpv 0.41 has no `program` property. Other tower: `engine/tower_dump.py` holds the tuner open; `tune <Hz>` truncates live.ts, ~3 s lock, black until the frame. j and k change channel. Left and right skip.

Window, follower: `yagi-live.slice`; Close TV stops it. Dumps: `yagi-dump<N>.scope`, `-tuner.slice`; copied ones outlive Close. Recorders: `-rec.slice`.

Guide is broadcast EIT only, every 3h on a free tuner; it yields to live at once. Listings reach ~5h. Network names are a hand-typed Cleveland map, not broadcast. Rescan rewrites the lineup; each Guide read fixes PIDs from the PMT. All = not hidden.

Tests: `python3 -m unittest` from the root; `tests/__init__.py` sandboxes XDG. Never `/tmp`.

Richard: ADD. Dry sarcasm, short. One task first. Every reply ends with the open list: numbered, letters for choices. Before any install, say what, from where, and how trusted.

Super+W quits. The HUD starts detached `sync --reap`; it deletes `live.ts` once the window and tune lock are gone.

Recordings: sidecar JSON, active once growing, stop under 8 GB free. The oneshot timer (`record due` each minute) kills its children, so recorders, finish, and its Guide update use `own_scope`. Timer runs `~/.local/share/yagi/current`, the last commit, never the working tree; republishes on a new HEAD. Series = title + channel, any hour. Back-to-back airings are one run; `record finish` splits them and marks ads. HUD skips each break once; library seeks: `byte_rate` to bytes, then `start=<pct>%` (`#N` is a chapter). Cap: keep_last, then series first; never locked or newest. Save (y) copies the pause. Live picture is one fd://0 reader on the follow fifo.
