"""Loaded only by the CLI window tests. Play must not open a tuner."""

from engine.timeshift import TIMESHIFT_FILE, Timeshift


def _keep_dump(cls, tune_name, adapter_id=None, keep_follow=False):
    if not (tune_name or "").strip():
        return None
    cls.ensure_dir()
    return TIMESHIFT_FILE


Timeshift.start_dump = classmethod(_keep_dump)
Timeshift.retune_keep_window = classmethod(_keep_dump)
