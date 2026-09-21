# Omarchy TV — Architectural Design

> Digital television on the modern Linux desktop should feel like a first-class Wayland app, not a 2008 backend with a skin.

---

## 1. Thesis

Kaffeine, MythTV, and Tvheadend grew up on X11, modal dialogs, and always-on backends. MythTV wants a database just to watch the news. Kaffeine flags legal OTA streams as scrambled because PSIP left `access_controlled` set.

Omarchy TV is a **thin local appliance**:

- Quickshell for chrome (bar + flyout)
- Python for DVB, scan, EPG, DVR, timeshift
- MPV for decode, PiP, and the on-video HUD

No MySQL. No root. No second “frontend” process. If the bar plugin and `omarchy-tv` CLI are installed, you can scan, watch, pause live, and record.

---

## 2. Layers

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 1 — Quickshell (plugin/BarWidget.qml + Model.js)      │
│   Antenna icon, KeyboardPanel flyout, FileView on JSON      │
│   Does not paint key chords (HUD owns those)                │
└──────────────────────────────┬──────────────────────────────┘
                               │ IpcHandler + atomic JSON
┌──────────────────────────────▼──────────────────────────────┐
│ Layer 2 — Python engine                                     │
│   tuner · scanner · enrichment · guide                      │
│   dvr (Videos/TV library) · timeshift (live.ts dump)        │
│   paths ($XDG_RUNTIME_DIR sockets, XDG config/cache/videos) │
└──────────────┬───────────────────────┬──────────────────────┘
               │                       │
        ┌──────▼──────┐         ┌──────▼──────┐
        │ Layer 3     │         │ Layer 4     │
        │ Linux DVB   │         │ MPV + lua   │
        │ /dev/dvb    │         │ PiP / HUD   │
        └─────────────┘         └─────────────┘
```

There is no `Panel.qml`. The flyout **is** `BarWidget.qml`’s `KeyboardPanel`.

---

## 3. Design rules

### A. Dual-tuner leases

Hauppauge WinTV-dualHD is two adapters. `TunerManager.get_available_tuner()` prefers:

| Role | Adapter | Why |
| --- | --- | --- |
| Live dump + pause-live file | 0 | Headless MPV `--stream-dump` of `dvb://` into `live.ts` |
| Scan, EPG refresh, library record | 1 | Must not steal the live frontend |

Background work **must** drop `/dev/dvb/adapter*/frontend0` before MPV opens the same adapter (`EBUSY`).

### B. ATSC +28.615 kHz

Nominal centers (`177000000`) miss the A/53 pilot. Every table entry is `nominal + 28615`. Scan dwell is at least **1.2 s** so 8VSB can lock.

### C. Two different “recordings”

| | Library DVR | Pause-live (timeshift) |
| --- | --- | --- |
| Purpose | Keep a show | Freeze now, skip in the buffer, catch live |
| Tuner | 1 | 0 (dump only; the PiP does not open DVB) |
| Path | `$XDG_VIDEOS_DIR/TV` (default `~/Videos/TV`) | Growing `live.ts` under `$XDG_CACHE_HOME/omarchy/tv/timeshift` |
| Indexed in Recordings | Yes | Never |
| Length | Until stop / duration arg | Until channel change, Close TV, or a cap we have not proven |
| Discard | User delete / library cap | Channel change, return from a library file, or Close TV |

`r` is library record. `Space` on live is pause-live. Those can run together: dump/pause on Tuner 0, record on Tuner 1.

The PiP is **always file-only MPV** (no `dvbin` in the window). Live is a never-EOF follow pipe of `live.ts` (mpv 0.41 `keep-open` does not follow a growing file — it hits EOF at the size it opened). Library playback is a file in `Videos/TV`. There is one windowed MPV on the follow pipe (`--force-window=immediate` so Hyprland maps it before the first frame). Do not spawn an idle PiP with no file, and do not unlink the IPC socket and launch a second `omarchy-tv` class while an old window is still alive.

### D. Return to live

A finished library recording, or a seek that reaches the end of that file, should call `return_to_live()` and retune the last live station. MPEG-TS often reports `duration` 0, so the HUD estimates length from file size at the ATSC rate (~19.39 Mbps), seeks by byte offset, and treats the last 15s skip (or EOF) as return-to-live.

On live TV, a headless MPV dumps the station to `live.ts` while a follow process copies that file to the PiP’s stdin, waiting at EOF so the picture keeps moving. Pause stops the reader; the dump keeps writing. Skip is a byte-offset SEEK on the follow socket (same 188-byte TS alignment as a library recording). `l` / catch-up seeks the write head. `→` while already on the write head flashes LIVE and does not jump the bar. Channel change stops the dump, wipes `live.ts`, and starts a new dump + one new window. Do not play `dvb://` in the PiP — mpv 0.41 `dvbin` cache is not seekable. `drop-buffers` desyncs the tuner and must not be used.

### E. Reactive UI, atomic state

Scanner, DVR, and player write JSON via `.tmp` + `os.replace`. Quickshell `FileView` binds those files. `player_state.json` is the now-playing contract; `omarchy-tv sync` / MPV shutdown / dead-pid reconcile clear it when the window is already gone. Cmd+W is Close TV for the leftover dump, but `sync` must not wipe a dump while a retune lock is held (channel click starts dump before the new window exists).

### F. Zero privilege

User session ACLs on `/dev/dvb/*`. Sockets from `engine.paths.get_runtime_socket()` inside `$XDG_RUNTIME_DIR` (0700). Process argv arrays, never shell strings.

### G. Theming and chrome

QML uses `Color.*`, `Style.space()`, `Style.font.*`, `root.bar.*`. Plugin must not hardcode keybinding labels. Player keys live in `player/scripts/tv_hud.lua`.

### H. Hyprland PiP

```lua
o.window("omarchy-tv", {
  float = true,
  pin = true,
  size = { 720, 405 },
  keep_aspect_ratio = true,
  opacity = "1 1",
  move = { "(monitor_w-window_w-40)", "(monitor_h-window_h-40)" },
})
```

Fullscreen is a compositor toggle (`hyprctl eval` on that class), not MPV’s own fullscreen, so geometry restores.

---

## 4. Flyout layout

While live, the channel list is hidden. **Guide** opens a nearly full-monitor `KeyboardPanel` (`availableCardWidth` / ~92% height) with a 6:00 PM–11:00 PM grid: as many half-hour columns as fit, arrows for the rest. Channel list stays about a third of the display when Guide is closed.

---

## 5. Library budget

`DvrManager.enforce_library_budget` deletes oldest **finished** files until usage fits:

- `pref library-max auto` — ~20 GB, reduced on small or full volumes
- a numeric GB cap
- `off` — no prune

Timeshift cache files are not in this budget.
