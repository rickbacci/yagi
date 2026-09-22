# AGENTS.md — Omarchy TV

OTA TV for Omarchy (Hyprland + Quickshell + Python + MPV). Current idea: `DESIGN.md` and `skills/omarchy-tv/SKILL.md`. This file is repo rules only.

## Commands
- Tests: `python3 -m unittest discover tests` (100% before commit)
- Status: `bin/omarchy-tv status`
- Reload widget: `omarchy restart shell`
- Hyprland: `hyprctl reload && hyprctl configerrors`

## Hard constraints
1. Unprivileged `$USER` only. No `sudo` / `pkexec`. Tuner ACLs are the active seat.
2. IPC sockets via `engine.paths.get_runtime_socket()` in `$XDG_RUNTIME_DIR` (0700). Never `/tmp/`.
3. ATSC frequencies keep `+28615` Hz. Never round to `000000`.
4. Tuner 0 for live dump; Tuner 1 for scan / EPG / library record. A recording holds Tuner 1 — do not steal it. Idle Tuner 1 may lock the next station.
5. State JSON: write `.tmp`, `os.replace`.
6. QML: `Color.*` / `Style.*` / `root.bar.*` tokens. No hardcoded key chords on the plugin (HUD owns those).
7. Hyprland class `omarchy-tv`: float, pin, 16:9, bottom-right, height `monitor/3`. Same chrome as `pip.lua`, not the `pip` tag or 600×338. Move uses the size expressions, not `window_w`. Pin is static; Super+F is `omarchy-tv fullscreen` (unpin first). No HUD `f`. No mpv `--window-dragging`; move is Super+LMB.
8. Release DVB frontends before a new dump (`EBUSY`).
9. Scan dwell ≥ 1.2 s.
10. Library recordings: `$XDG_VIDEOS_DIR/TV`. Pause-live dump: `$XDG_CACHE_HOME/omarchy/tv/timeshift/`. Not the same tree. PiP is never `dvb://`. Close TV wipes the dump, the sidecar, and any sidecar it lost track of.

## Settled
The picture overlay is settled (`player/scripts/tv_hud.lua`, `render_hud`). Leave that look alone. If work wants to change it, stop, say why the look has to change, and wait.

Dark top bar. Station color on the left edge. Channel number, network, station name, the show on now and its time. Right side: LIVE, PLAY, or how far behind. Under that, REC or Muted. A progress line on the bottom edge of this bar only while paused or behind live. Bottom bar is one control line: Pause or Play, Record or Stop, Live, Mute, and Vol plus the number. Behind live or a library file, that line adds Back 10s and Ahead 10s. Channel changes are the flyout list. Vol stays the number while muted. The word Muted stays on the top bar. Until the first frame, those two bars stay up and the middle stays empty. After a frame, they hide on their own.

A fix that does not change that look can land. Say so when it touches the overlay. Do not restyle, move, add, or drop a word, color, or bar to make another feature fit.

The flyout is settled too (`plugin/BarWidget.qml`). Same rule: stop, say why the look has to change, and wait.

Header: antenna icon, Omarchy TV, the channel count and how many favorites, then Recordings and Guide. Guide opens a strip in this same flyout: a search field, then one row per station with that name once and three hours of titles across, Earlier and Later, and the shows waiting to record. The flyout widens while that strip is open. Closed, that strip is gone and the flyout is only as wide as one line needs. One line outside it only when a show is waiting. Under the tuner rows, one line for what tuner 0 is doing: channel, show, Close. A recording is the same kind of line, with Stop. A Guide update uses that second line, “Updating the Guide,” and leaves when it finishes. A scan keeps its progress card. The channel list sits behind Show / Hide. It opens on favorites. Favs and Watchable are the lists you watch. All is the same stations with Hide on the right, and Hidden is where those stations go. Each station is one line: number, name, the show on now, and a star. A thin network-color edge sits on the left. The channel flyout and Recordings stay only as wide as one line needs.

## Working style
One task. If they batch asks, name the current task, park the rest on the todo list, finish that task before switching.

Talk first. Recommendation with pluses and minuses second. Numbered plan third. Code after they choose. Do not commit unless asked.

Obey **Hard constraints** and **Settled**. DESIGN / skill / README are the current idea, not a veto. The picture overlay and the flyout are. If the goal needs a path they don’t describe, advise that path, discuss, then proceed after we understand each other. Update them after it works. Do not stop to rewrite docs in order to think.

Read this machine’s mpv / Quickshell / Hyprland / DVB docs, not a remembered wiki.

## Done
They saw it, or the running app did. Green tests and “it’s in the lua” are not done. Clock-only HUD is not skip. If they still cannot see it: measure the prediction, record the miss, stop that theory.
