# What's left

Open:

- `plugin/README` for Omarchy plugin letters. `manifest.json` stays `0.1.0` until it is published as 1.0.0.
- The pause sidecar is loopback HTTP with no URL token. State JSON is not all `0600`.

The pause dump stops when it is an hour of air ahead of the playhead. The picture stays paused on the file already written. Close TV still deletes it. It is not a recording, and the library cap does not apply to it.

Skip is 10 seconds, 5 near live. Channel change dumps tuner 0, then `loadfile` in the same PiP. The picture overlay and the flyout are settled. The middle of a black picture stays empty.

First run is empty: no Hidden seed, no canned Guide, no RF map unless `station_map.json` is copied in. Tuner 0 is only live. Tuner 1 is only scan / Guide / record.
