# Failed predictions (read when pause/skip/HUD still looks wrong)

Do not retry these. Probe `path`, `eof-reached`, `time-pos` first.

- `dvb://` + mpv cache is not WinTV. `seek` returned success; `time-pos` did not move. `loadfile` of the same URL did nothing.
- `keep-open` on growing `live.ts` hits EOF (~1s) and freezes. Do not play the dump file as a path. HTTP waits at EOF.
- In-process HTTP (daemon thread in `omarchy-tv play`) dies when play returns. mpv then `Connection refused` and exits (`Exiting... (Errors when loading file)`). Sidecar process.
- Idle PiP (`--force-window=immediate`, no file) + unlinking the IPC socket while an old window lives = second black `omarchy-tv`.
- `--force-window=yes` on a pipe: CLI said running, Hyprland had no client until the first frame.
- 3s IPC wait lied: dump lock takes longer; `play` exited 1 while dump/follow/mpv were still starting.
- Flyout second-click of the same channel killed the CLI and left a tuner-busy dump.
- Cmd+W cleared now-playing; dump kept the tuner; `sync` wiped a new dump before the window mapped. Hold the retune lock.
- `j` was stock `cycle sub` when HUD bindings failed to load. lua errors vanished (stderr to empty `hud.log`). Use `--log-file`. `osd-overlay` can abort the script on gpu-next; keys must still register.
- Overlay ASS was painting. Extra dump was `osd_message(KEY_LEGEND)` + LIVE at `osd-font-size` 72. `--osd-level=0`. Center LIVE splash duplicated the small badge.
- Pause clock: mpv stdin `file-size` freezes; dump still grows. Unpause `dur-virt_pos` looked LIVE. ATSC 19.39 Mbps turned 47s behind into 22s.
- SEEK/PACE on a follow feeder cannot rewind mpv. A pipe is not seekable. Skip is `loadfile` HTTP `from=` in this window, not `pip-relaunch`.
- `--window-dragging` (default yes) stole Super+LMB. Pin makes Super+F a no-op until `omarchy-tv fullscreen` unpins. No HUD `f` / double-click.
- `omarchy-tv prev` before the new dump exists closed the window. `loadfile -` quits this mpv. Named FIFO: corrupt probe, mpv exited.
- Reap by matching `omarchy/tv/timeshift/` in argv killed the PiP (`--log-file=.../hud.log`). Match `--stream-dump=` only.
- Retune every `j`/`k` froze picture and cut audio. Banner first; one commit after idle. HUD `play` is `detach=no` — quit from that child dies with the window; `pip-relaunch` is a new session.
- Same dump IPC socket across overlap: `stop_dump` killed the new dump. Alternate sockets. Recording on Tuner 1: skip overlap, retune Tuner 0.
- `m` is TV-only mute. Do not unmute on `tv-retuned`.
