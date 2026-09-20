# Omarchy TV — Architectural Design & Philosophy

> "Digital television on the modern Linux desktop shouldn't feel like an archaeology exhibit from 2008."

---

## 1. Thesis & Problem Space

Traditional Linux digital TV software (Kaffeine, MythTV, Tvheadend) was designed in the early 2000s under very different desktop assumptions:
- **X11 Toolkits & Archaic Modals**: Built around legacy Qt4/Qt5 or GTK2 widget dialogs that do not compose with modern Wayland compositors (Hyprland), lacking fluid scaling, hardware-accelerated animations, or theme inheritance.
- **Cryptic Metadata Warnings**: Applications like Kaffeine strictly evaluate ATSC digital flags, erroneously flagging 100% legal, unencrypted Over-The-Air broadcasts with a **red encrypted padlock** icon because local broadcasters leave an archaic `access_controlled` bit enabled in their PSIP VCT tables.
- **Monolithic Bloat**: MythTV requires an external MySQL database, separate backend/frontend daemons, and hundreds of configuration options just to watch a local news broadcast.
- **Slow, Brute-Force Scanning**: Old scanners blindly brute-force 70+ frequencies without accounting for pilot carrier offsets, taking 20+ minutes and locking the UI thread.

**Omarchy TV** rejects this entire paradigm. It approaches OTA television as a lightweight, first-class citizen of the modern Wayland desktop.

---

## 2. Architectural Layers

Omarchy TV is partitioned into four decoupled, asynchronously connected layers:

```
┌─────────────────────────────────────────────────────────────┐
│                 Layer 1: Quickshell Surface                 │
│   (~/.config/omarchy/plugins/richardb.omarchy-tv)           │
│   • BarWidget.qml: Antenna icon, scanning radar pulse       │
│   • Panel.qml: Glass-blurred PopupCard, Live RF HUD         │
│   • Model.js: Formatters, channel cleaner, theme mapping    │
└──────────────────────────────┬──────────────────────────────┘
                               │ IPC / FileView Reactive Pipeline
┌──────────────────────────────▼──────────────────────────────┐
│                  Layer 2: Core Python Engine                │
│   • engine/tuner.py: Dynamic multi-tuner allocator          │
│   • engine/scanner.py: ATSC scanner with +28.615 kHz offset │
│   • engine/paths.py: $XDG_RUNTIME_DIR security isolation    │
│   • engine/daemon.py: UNIX domain socket JSON-RPC server    │
└──────────────┬──────────────────────────────┬───────────────┘
               │                              │
        ┌──────▼──────┐                ┌──────▼──────┐
        │   Layer 3   │                │   Layer 4   │
        │ Hardware /  │                │ Playback /  │
        │ Linux DVB   │                │ MPV Wayland │
        │ (/dev/dvb)  │                │ (PiP / Lua) │
        └─────────────┘                └─────────────┘
```

---

## 3. Core Design Principles

### A. Dual-Tuner Intelligent Allocation
Hardware like the **Hauppauge WinTV-dualHD** exposes two independent tuner adapters (`/dev/dvb/adapter0` and `/dev/dvb/adapter1`).
- Legacy apps blindly seize `adapter0`, colliding with background jobs or causing `Device or resource busy` errors.
- Omarchy TV's `TunerManager` actively probes device availability via Linux `fuser` and frontend state.
- **Concurrency Rule**: Tuner 0 is preferentially reserved for low-latency live viewing, while Tuner 1 is dynamically leased for background frequency scanning, EPG table refreshes, and scheduled DVR recordings.

### B. Precision Carrier Tuning (+28.615 kHz Pilot Offset)
In the ATSC A/53 terrestrial digital TV specification:
- Nominal channel center frequencies (e.g. 177.0 MHz for Ch 7, 473.0 MHz for Ch 14) are not the actual digital carrier center.
- The ATSC DTV pilot carrier is transmitted **310 kHz above the lower channel edge**, resulting in an exact **+28.615 kHz offset** (`+28615 Hz`).
- Omarchy TV hardcodes the exact pilot frequencies (e.g. `177028615 Hz`, `473028615 Hz`). This allows the tuner's carrier recovery loop to achieve instant lock within 1.0–1.5 seconds per transponder instead of drifting and timing out.

### C. The Live RF HUD & Reactive State
Instead of blocking the GUI or forcing the user to guess if a scan is frozen:
1. The scanner yields atomic state updates for physical frequency, band, instantaneous signal dBm, and virtual stations.
2. Updates are written atomically via POSIX `os.replace` to `~/.config/omarchy/tv/scan_status.json`.
3. Quickshell's reactive `FileView` binds the JSON data directly into QML properties.
4. The UI renders an **Animated Gradient Progress Bar** (`Easing.OutQuad`) paired with a live **RF Tuner Lock HUD** showing real-time dBm signal strength and discovered station badges.

### D. Zero-Privilege Security Boundary
- **No Root, No Sudo**: The entire stack operates as unprivileged user `1000:1000`.
- **Systemd Session ACLs**: Hardware access is granted via active seat permissions (`user:richardb:rw-` on `/dev/dvb/*`), requiring zero group modifications or setuid privileges.
- **Isolated Sockets**: Sockets (`omarchy-tv-mpv.sock` and `omarchy-tv-daemon.sock`) are anchored in `$XDG_RUNTIME_DIR` (`/run/user/1000/`) with strict `0700` filesystem masks, immune to local user tampering.
- **Injection-Proof Process Spawning**: All process executions in both Python and QML pass discrete argument arrays (`["omarchy-tv", "play", channel]`) with `shell=False`.

### E. Declarative Hyprland Integration
Instead of forcing fullscreen or hardcoded X11 geometry, Omarchy TV leverages Omarchy’s native Hyprland Lua DSL:
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
This guarantees that whenever TV video is launched:
- It floats in a true 16:9 aspect-ratio window.
- It pins as a seamless Picture-in-Picture (PiP) window across all active Hyprland workspaces.
- It snaps to the bottom-right corner of the active display without covering system widgets.
