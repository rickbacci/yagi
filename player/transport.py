"""Pause and skip for the one live window.

The controller launches mpv. This module decides where the fifo reader sits.
"""

from typing import Optional


def _ts():
    from player.controller import Timeshift

    return Timeshift


def _paths():
    from player.controller import is_follow_path, is_timeshift_path

    return is_timeshift_path, is_follow_path


class Transport:
    def __init__(self, player) -> None:
        self.player = player

    def open_dump(self, byte: int, paused: bool) -> bool:
        """Channel change. The only loadfile, under the black cover already up."""
        from player.controller import align_ts

        ts = _ts()
        byte = align_ts(byte)
        if not ts.start_follow(byte):
            return False
        ts.send_follow_reopen()
        ts.send_follow_seek(byte)
        # A zap is the station now. Pacing from the start of the file falls behind.
        self.arm(paused, False)
        self.player._load_dump("fd://0")
        self.player.send_command(["set_property", "pause", paused])
        self.note(byte, paused)
        return True

    def behind(self, byte: int) -> bool:
        from player.controller import LIVE_SLACK

        ts = _ts()
        rate = ts.write_rate()
        if rate <= 0:
            return False
        return (ts.dump_bytes() - byte) / rate > LIVE_SLACK

    def arm(self, paused: bool, delayed: bool) -> None:
        """Pause freezes the cursor. Play behind paces. Live races the write head."""
        ts = _ts()
        if paused:
            ts.send_follow_pause()
            self.player.send_command(["set_property", "speed", 1])
            return
        ts.send_follow_play()
        self.player.send_command(["set_property", "speed", 1])
        if delayed:
            ts.send_follow_pace(ts.write_rate())
        else:
            ts.send_follow_catchup()

    def note(self, byte: int, paused: bool) -> None:
        from player.controller import LIVE_SLACK

        ts = _ts()
        rate = ts.write_rate()
        remain = 0.0 if rate <= 0 else max(0.0, (ts.dump_bytes() - byte) / rate)
        view = "live" if remain <= LIVE_SLACK else "delayed"
        ts.patch_state(
            view=view,
            paused=paused,
            playhead_byte=byte,
            skip_busy=False,
        )

    def seek_cursor(self, byte: int, paused: bool) -> bool:
        """Move the reader. The window stays on the fifo it already has open."""
        from player.controller import align_ts

        ts = _ts()
        byte = align_ts(byte)
        if not ts.send_follow_seek(byte):
            # Replacing a live reader unlinks the fifo the window already has open.
            pid = int(ts.load_state().get("follow_pid") or 0)
            if ts._pid_alive(pid) or not ts.start_follow(byte) or not ts.send_follow_seek(byte):
                return False
        # The readahead is the old picture. Drop it so the keyframe break is next.
        self.player.send_command(["drop-buffers"])
        self.arm(paused, self.behind(byte))
        self.player.send_command(["set_property", "pause", paused])
        self.note(byte, paused)
        return True

    def playing(self, path: Optional[str]) -> bool:
        is_file, is_follow = _paths()
        return is_file(path) or is_follow(path)

    def toggle_pause(self) -> None:
        from player.controller import LIVE_SLACK, align_ts

        player = self.player
        if not player.is_running():
            return
        path = player._mpv_path()
        if not self.playing(path):
            player.send_command(["cycle", "pause"])
            return
        ts = _ts()
        state = ts.load_state()
        paused = bool(state.get("paused"))
        if not paused:
            ts.send_follow_pause()
            cursor = ts.follow_pos()
            if cursor is None:
                if str(state.get("view") or "live") == "live":
                    cursor = ts.live_edge_byte()
                else:
                    cursor = int(state.get("playhead_byte") or 0)
            player.send_command(["set_property", "pause", True])
            ts.patch_state(paused=True, playhead_byte=align_ts(cursor))
            return
        cursor = ts.follow_pos()
        if cursor is None:
            cursor = int(state.get("playhead_byte") or 0)
        cursor = align_ts(cursor)
        delay = ts.delay_sec()
        self.arm(False, delay > LIVE_SLACK)
        player.send_command(["set_property", "pause", False])
        view = "delayed" if delay > LIVE_SLACK else "live"
        ts.patch_state(paused=False, view=view, playhead_byte=cursor)

    def seek(self, seconds: float) -> bool:
        from player.controller import align_ts

        player = self.player
        if not player.is_running():
            return False
        path = player._mpv_path()
        if not self.playing(path):
            res = player.send_command(["script-message", "tv-seek", str(seconds)])
            return res is not None and res.get("error") == "success"
        ts = _ts()
        delta = float(seconds or 0)
        if delta == 0:
            if bool(ts.load_state().get("paused")):
                return True
            if ts.delay_sec() > 0.15:
                return self.seek_cursor(ts.playhead_now(), paused=False)
            return player.return_to_live()
        if ts.load_state().get("skip_busy"):
            return True
        ts.patch_state(skip_busy=True)
        try:
            state = ts.load_state()
            paused = bool(state.get("paused"))
            view = str(state.get("view") or "live")
            rate = ts.write_rate()
            pos = ts.follow_pos()
            if pos is None:
                pos = int(state.get("playhead_byte") or ts.playhead_now())
            remain = 0.0 if rate <= 0 else max(0.0, (ts.dump_bytes() - pos) / rate)
            if delta > 0:
                hop = ts.fwd_hop(remain)
                if hop <= 0:
                    return player.return_to_live()
                return self.seek_cursor(align_ts(int(pos + hop * rate)), paused)
            if view == "live" and not paused:
                hop = abs(delta)
                byte = align_ts(max(0, int(ts.dump_bytes() - hop * rate)))
                return self.seek_cursor(byte, paused=False)
            pos = max(0, int(pos - abs(delta) * rate))
            return self.seek_cursor(align_ts(pos), paused)
        finally:
            ts.patch_state(skip_busy=False)
