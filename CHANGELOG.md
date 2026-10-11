# Changelog

## 0.1.5

- A missing `fuser` is treated as busy. The library size cap will not delete the recording you are watching when it cannot tell which files are open.
- Tests: the bar is instantiated with Qt 6 against a checked-in Omarchy stub, and that load fails on the 0.1.1 widget that put a hover handler in the keyboard panel.

## 0.1.4

- The bar widget loads again. Guide search imports Quickshell and Quickshell.Io, which provide Process and StdioCollector. Without those imports the shell rejected the page.

## 0.1.3

- Guide search is not an editable text field until you open it. While it is open it stays read-only to Qt, so a foreign clipboard cannot stall the shell. Paste is capped and timed out. The search text stays off the command line.

## 0.1.2

- The bar widget loads again. The hover handler sits on the key catcher. KeyboardPanel only accepts items, and a handler placed there stopped the plugin from loading.

## 0.1.1

- The Guide grab runs as its own user service, so the record timer exiting no longer kills it.
- A dvbv5 audio or video PID with several numbers (for example `52 53`) no longer aborts the rest of the towers.
- An empty Guide read is not counted as success. The reason is in the journal and `guide_status.json`, and the next try waits.
- Opening the Guide with no current listings starts a refresh when a tuner is free, and says so when one is not.
- An empty Favorites list says to open All and star a channel. The channel filter is remembered.
- Marking ads on a finished recording runs as its own user service, so the timer cannot kill Comskip or ffmpeg. The unit name is a random id, with no show title, channel, or file path.
- `f` or a double-click in the picture fullscreens it. Esc, `f`, or another double-click returns to the small pinned window. The Hyprland rule must not pin that window.
- 1080i and 480i are deinterlaced. Progressive 720p is left alone. `i` shows player stats.
- The channel, Guide, and recordings highlight clears when the pointer leaves the row or the panel.
- The picture opens at the volume and mute it had when it last closed. The first open is unmuted at normal volume.
