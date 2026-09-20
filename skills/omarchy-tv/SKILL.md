---
name: omarchy-tv
description: >
  Control Over-The-Air (OTA) television on Omarchy systems using the Omarchy TV
  suite and Hauppauge dual-tuner hardware. Use when asked to tune/play channels, scan for
  broadcast stations, inspect antenna signal strength, surf channels, or manage digital TV tuners.
  Triggers: TV, watch TV, live TV, OTA, antenna, broadcast, tuner, ATSC, channels, scan channels.
---

# Omarchy TV Skill

Control and automate live Over-The-Air digital broadcast television on Omarchy (Hyprland + Quickshell + MPV).

## Quick Actions

### 1. Channel Tuning & Playback
To tune into a channel or launch the floating Picture-in-Picture player:
```bash
# Play a channel by virtual channel number or callsign
omarchy-tv play "53.1 Daystar"

# Channel surfing controls
omarchy-tv next
omarchy-tv prev

# Stop video playback
omarchy-tv stop
```

### 2. Quickshell Desktop IPC Controls
Alternatively, control the active status bar widget and player without spawning subshells:
```bash
omarchy-shell shell broadcast richardb.omarchy-tv play "53.1 Daystar"
omarchy-shell shell broadcast richardb.omarchy-tv next
omarchy-shell shell broadcast richardb.omarchy-tv prev
omarchy-shell shell broadcast richardb.omarchy-tv stop
omarchy-shell shell broadcast richardb.omarchy-tv reloadChannels
```

### 3. Check Tuner & Signal Status
To report hardware status or check antenna reception:
```bash
omarchy-tv status
```
Reads active tuners (`/dev/dvb/adapter*`), delivery systems (`ATSC`, `Clear QAM`), and player status.

For live RF frontend signal monitoring (SNR, dBm, Bit Error Rate) on tuner 0:
```bash
femon -H -a 0
```

### 4. Scan for Local Channels
```bash
# Fast ATSC scan (VHF-High + Core UHF: 30 frequencies)
omarchy-tv scan

# Full scan (all 68 frequencies including legacy VHF-Low)
omarchy-tv scan --full

# View saved channel list
omarchy-tv list
```

## System Architecture

- **Project Root**: `~/Projects/personal/omarchy-tv`
- **CLI Executable**: `~/Projects/personal/omarchy-tv/bin/omarchy-tv`
- **Channel Database**: `~/.config/omarchy/tv/channels.json`
- **MPV Config**: `~/.config/mpv/channels.conf`
- **Shell Plugin**: `~/.config/omarchy/plugins/richardb.omarchy-tv`

## Critical Rules
- **No Sudo**: All tools run strictly unprivileged under user permissions.
- **ATSC Carrier Offset**: Frequencies use exact `+28615` Hz pilot carrier offsets (ATSC A/53). Never edit frequencies to nominal zeros.
- **Hyprland Rules**: The player class is `omarchy-tv`, pre-configured in `~/.config/hypr/hyprland.lua` as a floating, pinned Picture-in-Picture window.
