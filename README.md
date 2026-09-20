# 📺 Omarchy TV (`richardb.omarchy-tv`)

[![Tests](https://img.shields.io/badge/tests-12%20passed-success)](tests/)
[![Platform](https://img.shields.io/badge/platform-Omarchy%20%7C%20Arch%20Linux-blue)](https://omarchy.org/)
[![Compositor](https://img.shields.io/badge/compositor-Hyprland-lightblue)](https://hyprland.org/)
[![UI Engine](https://img.shields.io/badge/ui-Quickshell%20(QtQuick%20%2F%20QML)-purple)](https://quickshell.outfoxxed.me/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A modern, native Over-The-Air (OTA) digital television suite crafted specifically for **Omarchy** (Arch Linux + Hyprland + Quickshell).

---

## 🌟 Why Omarchy TV?

Traditional Linux digital TV software (Kaffeine, MythTV, Tvheadend) was designed in the early 2000s with archaic X11 toolkits, confusing dialogs, and heavy legacy backends.

**Omarchy TV** brings digital broadcast television into the modern Wayland era:

* **Omarchy Shell Integration**: Clean antenna icon (`󰢹`) on your status bar with live state badges (`󰛳 63% Scanning` or active channel name).
* **Live RF HUD & Animated Progress**: Real-time signal strength meter in dBm, physical frequency readout, and smooth easing progress bar inside the popout card.
* **Dual-Tuner Intelligent Allocation**: Automatically manages dual tuners (e.g. Hauppauge WinTV-dualHD), allowing you to watch TV on Tuner 0 while Tuner 1 scans frequencies or records in the background.
* **Exact ATSC Pilot Carrier Offsets**: Hardcodes exact +28.615 kHz carrier offsets (e.g., `177028615 Hz`), guaranteeing immediate carrier lock on modern demodulators.
* **Picture-in-Picture (PiP) Window Rules**: Powered by `mpv` with hardware VA-API/NVDEC decoding, automatically pinned across all Hyprland workspaces in a floating 16:9 frame.
* **Zero-Privilege Security**: Runs 100% unprivileged (`$USER`) using systemd user ACLs and secure runtime sockets in `$XDG_RUNTIME_DIR`.
* **Quickshell IPC Bridge**: Fully controllable via keyboard shortcuts or CLI broadcast commands.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                 Omarchy Bar Widget & Panel                  │
│       (~/.config/omarchy/plugins/richardb.omarchy-tv)       │
│        Quickshell (QML) • Native Theme Colors & Glass Blur  │
└──────────────────────────────┬──────────────────────────────┘
                               │ IPC / FileView Reactive Pipeline
┌──────────────────────────────▼──────────────────────────────┐
│                    Omarchy TV Core Engine                    │
│        (Python 3 • Linux DVB API • Multi-Tuner Allocator)    │
├──────────────────────────────┬──────────────────────────────┤
│    ATSC Hardware Scanner     │    Secure Runtime Sockets    │
│  (Real-Time RF HUD & Sync)   │   ($XDG_RUNTIME_DIR, 0700)   │
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
├── README.md                           # Master project guide
├── DESIGN.md                           # Architectural design document
├── HARDWARE_AND_TROUBLESHOOTING.md     # Tuners, RF signals, and ATSC guide
├── LICENSE                             # MIT License
├── .gitignore
├── bin/
│   └── omarchy-tv                      # Unified CLI entrypoint
├── engine/
│   ├── __init__.py
│   ├── paths.py                        # Secure $XDG_RUNTIME_DIR socket resolution
│   ├── tuner.py                        # Multi-tuner hardware allocator
│   ├── scanner.py                      # ATSC scanner with live signal metering
│   └── daemon.py                       # UNIX domain socket JSON-RPC server
├── player/
│   ├── __init__.py
│   ├── controller.py                   # MPV controller via JSON IPC socket
│   └── hyprland_rules.conf             # Hyprland window rules reference
├── plugin/                             # Omarchy Shell Plugin (symlinked to ~/.config)
│   ├── manifest.json                   # Quickshell plugin manifest (schemaVersion 1)
│   ├── BarWidget.qml                   # Status bar widget and Live RF HUD popout
│   └── Model.js                        # Theme colors, station cleaner, formatters
└── tests/                              # Automated unit test suite
    ├── test_frequencies.py             # ATSC frequencies & pilot carrier offsets
    ├── test_paths.py                   # Socket security and fallback permissions
    ├── test_scanner_parser.py          # ATSC virtual channel parser & serialization
    └── test_tuner.py                   # Tuner discovery and adapter capability
```

---

## ⚡ Quickstart

### 1. Link Plugin to Omarchy
```bash
# Symlink plugin directory into Omarchy user plugins
ln -sfn ~/Projects/personal/omarchy-tv/plugin ~/.config/omarchy/plugins/richardb.omarchy-tv

# Add to your status bar
omarchy bar put richardb.omarchy-tv --section right
```

### 2. Configure Hyprland Window Rules
Ensure the following rule is in your `~/.config/hypr/hyprland.lua`:
```lua
-- Omarchy TV (PiP / Floating Over-The-Air Player)
o.window("omarchy-tv", {
  float = true,
  pin = true,
  size = { 720, 405 },
  keep_aspect_ratio = true,
  opacity = "1 1",
  move = { "(monitor_w-window_w-40)", "(monitor_h-window_h-40)" },
})
```
Reload Hyprland:
```bash
hyprctl reload && hyprctl configerrors
```

### 3. Launch & Scan
1. Click the **TV icon** (`󰢹`) on your Omarchy top bar.
2. Click **"Scan OTA Channels"**.
3. Watch the **Live RF HUD** lock frequencies and discover local broadcast stations in real time!

---

## 🖥️ Command-Line Interface (`omarchy-tv`)

The `omarchy-tv` CLI is located at `bin/omarchy-tv`. You can add it to your `PATH` or invoke it directly:

```bash
# Check tuner availability and running player
bin/omarchy-tv status

# Run a fast ATSC broadcast scan (VHF-High + UHF: 30 frequencies)
bin/omarchy-tv scan

# Run a full scan across all 68 frequencies (including legacy VHF-Low & UHF)
bin/omarchy-tv scan --full

# List all discovered channels
bin/omarchy-tv list

# Tune into a channel
bin/omarchy-tv play "53.1 Daystar"

# Channel surfing controls
bin/omarchy-tv next
bin/omarchy-tv prev
bin/omarchy-tv stop
```

---

## 🎮 Desktop Keybindings & Quickshell IPC

Omarchy TV exposes an `IpcHandler` targeting `"richardb.omarchy-tv"`. You can bind any global shortcut in `~/.config/hypr/bindings.lua`:

```lua
-- Example: Channel surfing with media keys
o.bind("XF86AudioNext", "exec", "omarchy-shell shell broadcast richardb.omarchy-tv next")
o.bind("XF86AudioPrev", "exec", "omarchy-shell shell broadcast richardb.omarchy-tv prev")
o.bind("SUPER, F12",   "exec", "omarchy-shell shell broadcast richardb.omarchy-tv stop")
```

---

## 🧪 Automated Testing

Omarchy TV includes a comprehensive test suite using Python's standard `unittest` framework:

```bash
cd ~/Projects/personal/omarchy-tv
python3 -m unittest discover tests -v
```

Output:
```
test_bands (test_frequencies.TestAtscFrequencies.test_bands) ... ok
test_full_scan_count (test_frequencies.TestAtscFrequencies.test_full_scan_count) ... ok
test_pilot_carrier_offsets (test_frequencies.TestAtscFrequencies.test_pilot_carrier_offsets) ... ok
test_quick_scan_count (test_frequencies.TestAtscFrequencies.test_quick_scan_count) ... ok
test_fallback_socket_permissions (test_paths.TestPathsSecurity.test_fallback_socket_permissions) ... ok
test_socket_constants (test_paths.TestPathsSecurity.test_socket_constants) ... ok
test_xdg_runtime_socket (test_paths.TestPathsSecurity.test_xdg_runtime_socket) ... ok
test_parse_scan_output (test_scanner_parser.TestScannerParser.test_parse_scan_output) ... ok
test_save_channels (test_scanner_parser.TestScannerParser.test_save_channels) ... ok
test_write_scan_status_atomic (test_scanner_parser.TestScannerParser.test_write_scan_status_atomic) ... ok
test_get_available_tuner (test_tuner.TestTuner.test_get_available_tuner) ... ok
test_tuner_discovery (test_tuner.TestTuner.test_tuner_discovery) ... ok

Ran 12 tests in 0.370s
OK
```

---

## 📖 Additional Documentation

* **[Architectural Design (`DESIGN.md`)](DESIGN.md)**: Deep dive into the architectural layers, multi-tuner concurrency model, and security boundary.
* **[Hardware & Troubleshooting (`HARDWARE_AND_TROUBLESHOOTING.md`)](HARDWARE_AND_TROUBLESHOOTING.md)**: Complete guide on Hauppauge dualHD hardware, pilot carrier offsets, signal dBm interpretation, and the false "scrambled padlock" quirk.
* **[License (`LICENSE`)](LICENSE)**: MIT License.
