# What's left

Next up, in order (Richard's choices, Sep 27):

1. Release cleanup, then publish 0.1.0 as a fresh single-commit repo: README for strangers, trim personal lines from `AGENTS.md` and the docs, move `MEMORY.md` facts into code comments, untrack `MEMORY.md`, `.cursor/rules/`, and this file, fresh-clone install test in a scratch HOME. Undecided: (a) where to publish, GitHub or a Cursor-hosted repo; (b) ship `markets/cleveland.json` as the example market or leave it out; (c) submit the Omarchy plugin listing after the fresh-clone test or later.
2. Scratch cleanup: `mockups/`, `.icons/`, `icon-preview/`, `.worktrees/components`, `.lint/`, `.t/`, and `~/.cache/yagi/trim-backup` once the trimmed M*A*S*H and Cartoon All-Stars look right.
3. After 0.1.0: move state and actions out of `plugin/BarWidget.qml` (about 1,950 lines).
4. Undecided, low priority: show damaged video as blocks (now) or skip broken frames (short freezes).

Open:

- `plugin/README` for Omarchy plugin letters. `manifest.json` stays `0.1.0` until it is published as 1.0.0.
- State JSON is not all `0600`.
- Comskip marks ad breaks, with ffmpeg black-frame and silence detection as the fallback when Comskip's answer is not believable. Comskip has run on real episodes; the ffmpeg fallback only on generated clips.
- While you watch one tower and something records another, both tuners are busy and the Guide can't update. A long marathon then runs out of listings (about 5 hours) and stops until the next update.
- A recorder that dies mid-run is marked finished; the rest of that run is not restarted.
- Network names come from `markets/cleveland.json`, typed by hand. Nothing in the broadcast carries them.
- Live `live.ts` is never trimmed behind the playhead. The whole tower is about 8.7 GB an hour, so a long evening fills disk until Close TV.
- A zap to another tower is about 3 s of tuner lock plus the first picture. Only locking the next tower early on tuner 1 beats that, and that fights recordings and the Guide for the tuner. Parked.
- Captions on a whole-tower stream are not checked yet.
- Saving a pause (`y`) copies the whole tower, not one station.

The pause dump stops when it is an hour of air ahead of the playhead. The picture stays paused on the file already written. Close TV still deletes it. Save (`y`) copies the paused stretch into Recordings.

Skip is 10 seconds. Inside the last 10 seconds the next right arrow is live. A channel change keeps its tuner. On the same tower it switches tracks in the same picture, about a second; another tower retunes and reloads the same PiP. The middle of a black picture stays empty.

First run is empty: no Hidden seed, no canned Guide, no RF map unless `station_map.json` is copied in.
