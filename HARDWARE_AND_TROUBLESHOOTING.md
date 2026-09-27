# Yagi — Hardware

ATSC 1.0 / Clear QAM on Linux `DVBv5`. This box: Hauppauge WinTV-dualHD.

## DualHD (`2040:826d`, 955D / 1595)

LGDT3306A demod, Si2157 tuner, 8VSB + QAM64/256. Two adapters, `/dev/dvb/adapter0` and `/dev/dvb/adapter1`, shared by live TV, recordings, scans, and the Guide (`engine/pool.py`). Live prefers 0, the rest prefer 1. The PiP does not open `/dev/dvb`. Close `frontend0` before a new dump or Linux returns `EBUSY`.

Live TV holds its frontend open (`engine/tower_dump.py`) and reads the whole tower from `dvr0` with one all-PID filter, about 2.4 MB/s. On this box a lock to another tower takes 2.8–2.9 s, every time. The first tune after the frontend opens adds about 1 s while it wakes. A frontend that is closed and reopened, as mpv's `dvbin` does on every station change, pays that second each time, plus about 0.6 s in mpv's lock wait. Recordings still use mpv `dvbin`.

Seat ACLs, not `video` group, not root:

```bash
getfacl /dev/dvb/adapter0/frontend0   # expect user:<you>:rw-
getfacl /dev/dvb/adapter1/frontend0
loginctl show-session $(loginctl | awk '/seat0/{print $1}') -p Active
```

`femon` is optional. This box may not have it. SNR while a tune runs is on the flyout watch row. The live dump logs lock times and `SNR:` lines to `~/.cache/yagi/timeshift/dump.log`.

## Signal

While a tune is running, the flyout watch row shows SNR in dB. This demod reports that number in tenths: 223 is 22.3 dB. ATSC 8VSB wants about 15 dB. The strength percent is the same reading, scaled. The picture overlay only speaks up when it is Weak signal or No signal. `yagi signal` reads the tuner live TV is on.

Height and line-of-sight matter. VHF-High (7–13) wants longer elements. UHF (14–36) is most modern stations. Inside about 15 miles, an amp can overload the LGDT3306A.

## Why other apps show scrambled

OTA majors are unencrypted. Stations often leave PSIP `access_controlled` set. Kaffeine trusts that bit. We play the unencrypted elementary stream.

## +28.615 kHz

ATSC A/53: DTV pilot is 310 kHz above the lower band edge, i.e. nominal center **+28615 Hz**. Channel 7 is `177028615`, not `177000000`. Do not round `channels.conf` / `channels.json`.

## Paths

| What | Where |
| --- | --- |
| Channels, guide, now-playing, DVR index | `~/.config/yagi/` |
| Optional RF names | `~/.config/yagi/station_map.json` (copy `markets/cleveland.json`) |
| MPV channel table | `~/.config/mpv/channels.conf` |
| Library recordings | `~/Videos/TV` |
| Pause dump (whole tower) | `~/.cache/yagi/timeshift/live.ts` |
| Live dump and picture logs | `~/.cache/yagi/timeshift/dump.log`, `hud.log` |
| Sockets | `$XDG_RUNTIME_DIR/yagi-*.sock` |

Pause does not appear in Recordings. Use Record (`r`) or Save (`y`) for `Videos/TV`. The pause writer stops when the file is an hour of air ahead of the playhead. It grows about 8.7 GB an hour while the TV is open. Close TV still deletes it.
