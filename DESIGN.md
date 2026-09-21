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
│   dvr (Videos/TV library) · timeshift (cache buffer)        │
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
| Live watch | 0 | Low-latency dvbin in MPV |
| Scan, EPG refresh, library record, pause-live dump | 1 | Must not steal the live frontend |

Background work **must** drop `/dev/dvb/adapter*/frontend0` before MPV opens the same adapter (`EBUSY`).

### B. ATSC +28.615 kHz

Nominal centers (`177000000`) miss the A/53 pilot. Every table entry is `nominal + 28615`. Scan dwell is at least **1.2 s** so 8VSB can lock.

### C. Two different “recordings”

| | Library DVR | Pause-live (timeshift) |
| --- | --- | --- |
| Purpose | Keep a show | Freeze now, play from that moment |
| Tuner | 1 | 1 (dump) while 0 stays on the frozen live picture until Play |
| Path | `$XDG_VIDEOS_DIR/TV` (default `~/Videos/TV`) | `$XDG_CACHE_HOME/omarchy/tv/timeshift` |
| Indexed in Recordings | Yes | Never |
| Length | Until stop / duration arg | 15 minutes, then gone |
| Discard | User delete / library cap | Go live, retune, or Close TV |

`r` is library record. `Space` on live is pause-live. Mixing those is a product bug.

Playback of either is **file-only MPV** (no `dvbin`). Live tune always tears down timeshift first.

### D. Return to live

A finished library recording, EOF on a timeshift file, or a seek that reaches the end should call `return_to_live()` and retune the last live station. MPEG-TS often reports `duration` 0, so the HUD also watches `eof-reached` / `end-file` and “seek did not advance.”

### E. Reactive UI, atomic state

Scanner, DVR, and player write JSON via `.tmp` + `os.replace`. Quickshell `FileView` binds those files. `player_state.json` is the now-playing contract; `omarchy-tv sync` / MPV shutdown / dead-pid reconcile clear it when the window is already gone.

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

## 4. Flyout layout (current vs intended)

**Current:** `KeyboardPanel` uses `fittedContentWidth(Style.space(380))` and a 560-tall cap so the card lines up with other right-side Omarchy panels. While live, the channel list is hidden; Guide is a now/next pager.

**Intended:** size from the display — list about one third of the width (clamped), guide about half — with a horizontally scrollable evening grid (3–6 half-hour columns). `Model.js` already has `guideAllSlots` / `programBlocks`; `engine/guide.py` already attaches 6:00 PM–11:00 PM `programs`. The QML grid is not wired yet.

---

## 5. Library budget

`DvrManager.enforce_library_budget` deletes oldest **finished** files until usage fits:

- `pref library-max auto` — ~20 GB, reduced on small or full volumes
- a numeric GB cap
- `off` — no prune

Timeshift files are not in this budget.
