# Omarchy TV — Hardware Guide & Troubleshooting

Comprehensive guide for configuring Over-The-Air (OTA) TV tuners, understanding RF signals, and resolving common broadcast quirks on Omarchy.

---

## 1. Supported Hardware & Architecture

Omarchy TV is optimized for North American **ATSC 1.0** and **Clear QAM** digital television tuners using standard Linux `DVBv5` kernel drivers.

### Tested & Confirmed Hardware:
* **Hauppauge WinTV-dualHD**:
  - **USB ID**: `2040:826d` (Model 955D / 1595)
  - **Frontend / Demodulator**: LG Electronics LGDT3306A
  - **Tuner IC**: Silicon Labs Si2157
  - **Modulation**: 8VSB (ATSC OTA), QAM64 / QAM256 (Clear QAM Cable)
  - **Nodes**: Dual adapters exposed at `/dev/dvb/adapter0` and `/dev/dvb/adapter1`

Omarchy TV treats them as a pair, not two copies of the same app:

* **Adapter 0** — headless live dump (`--stream-dump` of `dvb://` into `live.ts`).
* **Adapter 1** — background scan and library recording.

The PiP plays `live.ts` (or a library file). It does not open `/dev/dvb`. If a Python scan or record still holds `frontend0` when the dump starts, Linux returns `EBUSY`. Background jobs must close those file descriptors before hand-off.

---

## 2. Permissions & Verification

Omarchy grants user access to TV tuners automatically via `systemd-logind` session Access Control Lists (ACLs). You **do not** need to add your user to the `video` group or run as `root`.

### Verify Tuner Access:
```bash
# Check device permissions and ACLs
getfacl /dev/dvb/adapter0/frontend0

# Expected output:
# user::rw-
# user:<username>:rw-   <-- Direct user access granted!
# group::rw-
# mask::rw-
# other::---
```

If your user account lacks `user:<username>:rw-`, verify your seat is active:
```bash
loginctl show-session $(loginctl | awk '/seat0/{print $1}') -p Active
```

---

## 3. Understanding the RF Signal & Live HUD

The **Live RF HUD** in Omarchy TV displays signal metrics directly from the demodulator:

### Signal Strength (dBm):
* **-15 dBm to -50 dBm (Strong / Green)**: Exceptional signal strength. Tower is nearby or antenna has high gain. Zero dropped packets.
* **-50 dBm to -70 dBm (Good / Blue)**: Reliable signal lock. Minor multipath reflection is easily corrected by forward error correction (FEC).
* **-70 dBm to -85 dBm (Fair / Amber)**: Marginal signal. You may occasionally see macroblocking or audio chirps during bad weather.
* **Below -85 dBm (Searching / Dim)**: Below demodulator threshold. Carrier cannot be locked.

### Antenna Positioning Tips:
1. **Line of Sight**: Place your antenna as high as possible, ideally near an exterior window facing toward your local broadcast transmitter towers.
2. **Frequency Bands**:
   - **VHF-High (Channels 7–13)**: Requires longer dipole elements (ears).
   - **UHF (Channels 14–36)**: Requires bow-tie or loop elements. Most modern stations broadcast here.
3. **Avoid Amplifiers if Close**: If you live within 15 miles of a broadcast tower, an active RF amplifier can overdrive the LGDT3306A frontend, causing signal overload and failed tuning.

---

## 4. Why Channels Show "Scrambled / Red Padlocks" in Other Apps

In applications like Kaffeine, users often report that scanned Over-The-Air broadcast stations appear with **red padlock icons** marked as "encrypted" or "scrambled".

### The Technical Reason:
- **FCC Mandate**: All primary ATSC 1.0 broadcast television channels (CBS, NBC, ABC, FOX, PBS, CW, etc.) are legally mandated by the FCC to be broadcast 100% unencrypted and free-to-air.
- **The PSIP Metadata Bug**: When stations encode their Terrestrial Virtual Channel Table (TVCT, ATSC A/65 Table 6.4), local station engineers frequently leave the `access_controlled` bit (Byte 26, `0x20`) set to `1`.
- **The Result**: Legacy applications strictly read this header flag and mark the station as "scrambled pay TV".
- **Omarchy TV's Handling**: Omarchy TV inspects the actual MPEG-2 / H.264 elementary streams. Because the stream payloads are completely unencrypted, Omarchy TV streams them without false warnings.

---

## 5. The +28.615 kHz Carrier Offset

If you attempt to tune or scan using nominal center frequencies (e.g. `177000000 Hz` for Channel 7 or `473000000 Hz` for Channel 14), the tuner may time out or fail to lock.

### The Math:
Under the ATSC A/53 specification, the DTV pilot carrier is inserted **310 kHz above the lower channel boundary**:
$$\text{Carrier Center} = \text{Nominal Center} + 28.615\text{ kHz}$$

* **Physical Channel 7**: $177.0\text{ MHz} + 28.615\text{ kHz} = \mathbf{177028615\text{ Hz}}$
* **Physical Channel 14**: $473.0\text{ MHz} + 28.615\text{ kHz} = \mathbf{473028615\text{ Hz}}$

Omarchy TV automatically pre-calibrates every scan table with these exact pilot offsets. Do not “round” frequencies in `channels.conf` or `channels.json`.

---

## 6. Where files live

| What | Path |
| --- | --- |
| Channels, guide, now-playing, DVR index | `~/.config/omarchy/tv/` |
| MPV channel table | `~/.config/mpv/channels.conf` |
| Keep-forever recordings | `~/Videos/TV` (`$XDG_VIDEOS_DIR/TV`) |
| Pause-live dump (`live.ts`) | `~/.cache/omarchy/tv/timeshift` |
| MPV / daemon sockets | `$XDG_RUNTIME_DIR/omarchy-tv-*.sock` |

If Recordings is empty after you hit Pause, that is expected: pause-live is not a library recording. Use **Record** (`r` on live TV) to write into `Videos/TV`.

---

## 7. Diagnostic & recovery commands

```bash
omarchy-tv status
omarchy-tv scan
omarchy-tv list
omarchy-tv play "8.1 FOX"
omarchy-tv pause
omarchy-tv live
omarchy-tv stop
omarchy-tv sync                 # now-playing still set after the window died
omarchy-tv record status
femon -H -a 0                   # live SNR / dBm on tuner 0
omarchy-shell shell broadcast richardb.omarchy-tv next
```

`omarchy-tv sync` (or reopen the flyout) clears a stale channel name after Super+W / compositor close and wipes the leftover dump. A channel click that is already retuning holds a lock so that sync cannot kill the new dump before the window maps.

---

## 8. Playback gotchas

* **No window / flyout thinks you are watching** — `--force-window=yes` waits for a video frame. Live uses `--force-window=immediate` on the follow pipe so the PiP maps as soon as MPV starts. An idle PiP (`--idle=yes`, no file) is still wrong — that is a second black window. A second click on the same channel while tuning used to kill the CLI and leave the dump holding the tuner. Close extras, then `omarchy-tv play`. Live is the follow pipe, not a snapshot of `live.ts` (`keep-open` hits EOF in about a second).
* **→ fills the bar / no red LIVE / `j` is captions** — lua HUD loads at MPV start. Close TV and retune after HUD edits. Stock mpv keys are off (`--input-default-bindings=no`). Lua errors go to `~/.cache/omarchy/tv/timeshift/hud.log` (`--log-file`). → at the write head should flash LIVE, not skip. Pointer-enter flashes `j/k` and the rest.
* **Left-drag moves the PiP without Super** — mpv `--window-dragging` default is yes. Live launch must pass `--window-dragging=no`. Omarchy move is Super+LMB.
* **Super+F does nothing** — Hyprland will not fullscreen a pinned window. Pin is static (applied at map). `omarchy-tv fullscreen` unpins, then the same dispatcher as Omarchy Super+F. Bare `f` is not a TV fullscreen key.
* **`j`/`k` freeze, no sound, picture never changes** — flash the full HUD banner; tune once after you stop. After the new dump exists, `pip-relaunch` remaps the PiP (stdin lavf will not switch muxes; `loadfile -` quit; quitting from HUD `play` killed the relaunch; a named FIFO probed corrupt and exited). `m` mutes only this window. HUD lua loads at MPV start.
* **Black screen on a recording** — dump was empty (under 256 KB) or MPV was still in dvbin mode. Library playback must be a file-only MPV instance.
* **Seek never reaches live** — live path is the follow pipe (`-`), not `dvb://`. `l` seeks the write head. Close TV and retune once if an old MPV process is still running.
* **Pause does not resume** — Space only cycles the PiP pause. Adapter 0 must still be dumping. Check `omarchy-tv status` if adapter 0 is stuck.
