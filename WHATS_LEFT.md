# What's left

Open:

- `plugin/README` for Omarchy plugin letters. `manifest.json` stays `0.1.0` until it is published as 1.0.0.
- State JSON is not all `0600`.
- Comskip is not installed (`omarchy-pkg-aur-add comskip`, needs sudo). Until then ad breaks come from ffmpeg black-frame and silence detection, untested on a real episode.
- While you watch and something records, both tuners are busy and the Guide can't update. A long marathon then runs out of listings (about 5 hours) and stops until the next update.
- A recorder that dies mid-run is marked finished; the rest of that run is not restarted.
- Network names come from `markets/cleveland.json`, typed by hand. Nothing in the broadcast carries them.

The pause dump stops when it is an hour of air ahead of the playhead. The picture stays paused on the file already written. Close TV still deletes it. Save (`y`) copies the paused stretch into Recordings.

Skip is 10 seconds. Inside the last 10 seconds the next right arrow is live. A channel change keeps its tuner, then `loadfile` in the same PiP. The middle of a black picture stays empty.

First run is empty: no Hidden seed, no canned Guide, no RF map unless `station_map.json` is copied in.
