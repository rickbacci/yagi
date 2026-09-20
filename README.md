# Omarchy TV (`omarchy.tv`)

A sleek, modern Over-The-Air (OTA) digital television suite crafted specifically for **Omarchy** (Arch Linux + Hyprland + Quickshell).

---

## 📺 Why Omarchy TV?

Traditional Linux digital TV software (Kaffeine, MythTV, Tvheadend) was designed in the early 2000s with archaic X11 toolkits, confusing dialogs, and heavy legacy backends.

**Omarchy TV** brings digital TV into the modern Wayland era:
- **Status Bar Integration**: Clean antenna icon in the Omarchy bar showing tuner status, current channel, and quick flyout menu.
- **Modern Channel Guide (EPG)**: Dynamic popout card styled to match your Omarchy theme (Catppuccin, Nord, Tokyo Night) with smooth glass blur.
- **Fast ATSC 1.0/3.0 Scanning**: Real-time progress updates (physical frequency, signal dBm, channels discovered) streamed over JSON.
- **Dual-Tuner Intelligent Allocation**: Automatically manages dual tuners (e.g. Hauppauge WinTV-dualHD) so you can watch live TV on Tuner 0 while Tuner 1 scans or records in the background.
- **Seamless MPV Playback**: Hardware-accelerated Wayland video engine with custom Hyprland window rules (floating 16:9, auto-pinned PiP, rounded corners, drop shadows) and keyboard shortcuts.
- **DVR & Scheduled Recording**: One-click instant recording directly to `~/Videos/TV/` plus a background scheduler for upcoming programs.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                 Omarchy Bar Widget & Panel                  │
│       (~/.config/omarchy/plugins/richardb.omarchy-tv)       │
│          Quickshell (QML) • Native Theme Colors & Blur       │
└──────────────────────────────┬──────────────────────────────┘
                               │ IPC (JSON-RPC / UNIX Socket)
┌──────────────────────────────▼──────────────────────────────┐
│                    Omarchy TV Core Engine                    │
│      (Python 3 • Linux DVB API • Dual-Tuner Allocator)      │
├──────────────────────────────┬──────────────────────────────┤
│    ATSC Hardware Scanner     │     EPG / PSIP Extractor     │
│  (Real-time JSON Progress)   │   (Live Broadcast Guide)     │
└──────────────┬───────────────┴──────────────┬───────────────┘
               │                              │
        ┌──────▼──────┐                ┌──────▼──────┐
        │ /dev/dvb/*  │                │  MPV Engine │
        │  (Hardware) │                │  (Wayland)  │
        └─────────────┘                └─────────────┘
```

---

## 📂 Project Structure

```
~/Projects/personal/omarchy-tv/
├── README.md
├── bin/
│   └── omarchy-tv              # Main CLI entrypoint
├── engine/
│   ├── __init__.py
│   ├── daemon.py               # Core Unix socket service & JSON API
│   ├── tuner.py                # Dual-tuner hardware allocator
│   ├── scanner.py              # ATSC frequency scanner & signal meter
│   └── epg.py                  # Live PSIP guide extractor
├── player/
│   ├── __init__.py
│   ├── controller.py           # MPV IPC controller (socket /tmp/omarchy-tv-mpv.sock)
│   └── hyprland_rules.conf     # Hyprland window rules (floating, PiP, rounded)
├── plugin/                     # Omarchy Quickshell Shell Plugin
│   ├── manifest.json
│   ├── BarWidget.qml           # Status bar icon & popup trigger
│   ├── Panel.qml               # Modern channel guide & tuner control card
│   ├── Model.js                # State management & IPC client
│   └── icons/
│       └── tv-antenna.svg
└── config/
    └── channels.default.json
```

---

## 🚀 Roadmap & Logical Chunks

1. **Phase 1: ATSC Hardware Engine & Fast Scanner**
   - Direct hardware interface to `/dev/dvb/adapter*`.
   - Real-time ATSC 8VSB frequency scanning with signal dBm reporting and virtual channel decoding.
   - Channel storage in clean JSON (`~/.config/omarchy/tv/channels.json`).

2. **Phase 2: MPV Player & Hyprland Window Management**
   - High-performance Wayland video playback using MPV.
   - Hyprland window rules for floating PiP, aspect ratio lock, and border effects.
   - MPV IPC socket controller for channel switching, volume, and OSD display.

3. **Phase 3: Omarchy Quickshell Bar Widget & Flyout Panel**
   - `BarWidget.qml`: Antenna icon with live tuning badge.
   - `Panel.qml`: Sleek channel list, station cards, now-playing info, and one-click scan wizard.

4. **Phase 4: Electronic Program Guide (EPG) & Station Metadata**
   - Parse live over-the-air PSIP program tables for instant offline "Now Playing" & "Up Next".
   - Optional internet XMLTV / Zap2it logo and description enrichment.

5. **Phase 5: DVR & Scheduled Recording**
   - Lossless one-click capture to `~/Videos/TV/`.
   - Background timer daemon for scheduled unattended recordings.
