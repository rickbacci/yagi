# Omarchy TV — Hardware

ATSC 1.0 / Clear QAM on Linux `DVBv5`. This box: Hauppauge WinTV-dualHD.

## DualHD (`2040:826d`, 955D / 1595)

LGDT3306A demod, Si2157 tuner, 8VSB + QAM64/256. Two adapters: `/dev/dvb/adapter0` (live dump to `live.ts`), `/dev/dvb/adapter1` (scan / library record). The PiP does not open `/dev/dvb`. Close `frontend0` before a new dump or Linux returns `EBUSY`.

Seat ACLs, not `video` group, not root:

```bash
getfacl /dev/dvb/adapter0/frontend0   # expect user:<you>:rw-
loginctl show-session $(loginctl | awk '/seat0/{print $1}') -p Active
femon -H -a 0
```

## RF

HUD dBm from the demod: about −15 to −50 strong, −50 to −70 good, −70 to −85 fair (weather hits), below −85 no lock. Height and line-of-sight matter. VHF-High (7–13) wants longer elements; UHF (14–36) is most modern stations. Inside ~15 miles, an amp can overload the LGDT3306A.

## Why other apps show scrambled

OTA majors are unencrypted. Stations often leave PSIP `access_controlled` set. Kaffeine trusts that bit. We play the unencrypted elementary stream.

## +28.615 kHz

ATSC A/53: DTV pilot is 310 kHz above the lower band edge, i.e. nominal center **+28615 Hz**. Channel 7 is `177028615`, not `177000000`. Do not round `channels.conf` / `channels.json`.

## Paths

| What | Where |
| --- | --- |
| Channels, guide, now-playing, DVR index | `~/.config/omarchy/tv/` |
| MPV channel table | `~/.config/mpv/channels.conf` |
| Library recordings | `~/Videos/TV` |
| Pause dump | `~/.cache/omarchy/tv/timeshift/live.ts` |
| Sockets | `$XDG_RUNTIME_DIR/omarchy-tv-*.sock` |

Pause does not appear in Recordings. Use Record (`r`) for `Videos/TV`.

Player/HUD misses for agents: `skills/omarchy-tv/failures.md`.
