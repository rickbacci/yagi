# Changelog

## 0.1.1

- The Guide grab runs as its own user service, so the record timer exiting no longer kills it.
- A dvbv5 audio or video PID with several numbers (for example `52 53`) no longer aborts the rest of the towers.
- An empty Guide read is not counted as success. The reason is in the journal and `guide_status.json`, and the next try waits.
- Opening the Guide with no current listings starts a refresh when a tuner is free, and says so when one is not.
- An empty Favorites list says to open All and star a channel. The channel filter is remembered.
- Marking ads on a finished recording runs as its own user service, so the timer cannot kill Comskip or ffmpeg. The unit name is a random id, with no show title, channel, or file path.
