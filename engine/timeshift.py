"""
Short pause-live buffer. Tuner keeps dumping while the picture is frozen;
unpause plays from that moment instead of jumping to live.
"""

import os
from typing import Optional

from engine.dvr import DvrManager, DvrSession
from engine.paths import TIMESHIFT_ACTIVE_PATH, TIMESHIFT_DIR, TIMESHIFT_SECONDS


class Timeshift:
    @classmethod
    def is_active(cls, active_path: Optional[str] = None) -> bool:
        return cls.active_session(active_path=active_path) is not None

    @classmethod
    def active_session(cls, active_path: Optional[str] = None) -> Optional[DvrSession]:
        sessions = DvrManager.load_active_sessions(active_path or TIMESHIFT_ACTIVE_PATH)
        for session in sessions:
            if session.is_active():
                return session
        return None

    @classmethod
    def buffer_path(cls) -> Optional[str]:
        session = cls.active_session()
        if session and session.file_path and os.path.isfile(session.file_path):
            return session.file_path
        newest = None
        newest_mtime = -1.0
        try:
            for name in os.listdir(TIMESHIFT_DIR):
                if not name.lower().endswith((".ts", ".mkv", ".mp4")):
                    continue
                path = os.path.join(TIMESHIFT_DIR, name)
                try:
                    mtime = os.path.getmtime(path)
                except OSError:
                    continue
                if mtime > newest_mtime:
                    newest = path
                    newest_mtime = mtime
        except OSError:
            return None
        return newest

    @classmethod
    def start(cls, channel_query: str) -> DvrSession:
        os.makedirs(TIMESHIFT_DIR, mode=0o755, exist_ok=True)
        existing = cls.active_session()
        if existing:
            return existing
        cls.stop(delete_file=True)
        return DvrManager.start_recording(
            channel_query,
            duration=TIMESHIFT_SECONDS,
            recordings_dir=TIMESHIFT_DIR,
            active_path=TIMESHIFT_ACTIVE_PATH,
        )

    @classmethod
    def stop(cls, delete_file: bool = True) -> None:
        stopped = DvrManager.stop_recording(active_path=TIMESHIFT_ACTIVE_PATH)
        if not delete_file:
            return
        for session in stopped:
            try:
                if session.file_path and os.path.isfile(session.file_path):
                    os.remove(session.file_path)
            except OSError:
                pass
        try:
            for name in os.listdir(TIMESHIFT_DIR):
                if name.lower().endswith((".ts", ".mkv", ".mp4")):
                    os.remove(os.path.join(TIMESHIFT_DIR, name))
        except OSError:
            pass
