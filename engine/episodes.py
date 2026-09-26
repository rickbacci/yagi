"""Back-to-back airings on one channel record as one run, then split into one file per episode.

Tuner 1 never stops between episodes, so none of them lose their first minute.
The timer notes the file size each minute. The split maps air time to bytes
from those notes and works from the last episode back, trimming the run as it
goes, so it needs room for about one episode, not a second copy.
"""

import os
import subprocess
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from engine.paths import chmod_private_file, state_lock
from engine.schedule import PAD_EARLY_SEC, PAD_LATE_SEC, item_window

# Two listings this close on one channel are one run. A skipped rerun in the
# middle does not make Tuner 1 let go; the split leaves its bytes out.
CHAIN_GAP_SEC = 65 * 60
MAX_MARKS = 2000
FINISH_LOCK_KEY = "recording-finish"
TS_PACKET = 188
COPY_CHUNK = 8 * 1024 * 1024


def _start(row: Dict[str, Any]) -> int:
    return int(row.get("start_unix") or 0)


def _end(row: Dict[str, Any]) -> int:
    return _start(row) + max(60, int(row.get("duration_sec") or 0))


def episode_of(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "title": str(row.get("title") or ""),
        "start_unix": _start(row),
        "duration_sec": max(60, int(row.get("duration_sec") or 0)),
        "synopsis": str(row.get("synopsis") or ""),
        "rule_id": str(row.get("rule_id") or ""),
    }


def follows(items: List[Dict[str, Any]], tune_name: str, after_end: int, after_start: int) -> List[Dict[str, Any]]:
    """Queued rows on this station that pick up where the last one ends, in order."""
    mine = sorted(
        [
            row for row in items
            if str(row.get("tune_name") or "") == tune_name
            and str(row.get("status") or "waiting") != "missed"
            and _start(row) > after_start
        ],
        key=_start,
    )
    run: List[Dict[str, Any]] = []
    end = after_end
    for row in mine:
        if _start(row) > end + CHAIN_GAP_SEC:
            break
        run.append(row)
        end = max(end, _end(row))
    return run


def chain_from(items: List[Dict[str, Any]], first: Dict[str, Any]) -> List[Dict[str, Any]]:
    tune = str(first.get("tune_name") or "")
    return [first] + follows(items, tune, _end(first), _start(first))


def run_stop(run: List[Dict[str, Any]]) -> int:
    """When Tuner 1 lets go: the last row's own window end."""
    return max(item_window(row)[1] for row in run)


def note_size(side: Dict[str, Any], now: float, size: int) -> List[List[int]]:
    marks = [m for m in (side.get("marks") or []) if isinstance(m, list) and len(m) == 2]
    if not marks or int(size) >= int(marks[-1][1]):
        marks.append([int(now), int(size)])
    return marks[-MAX_MARKS:]


def grow_runs(
    now: Optional[float] = None,
    schedule_path: Optional[str] = None,
    active_path: Optional[str] = None,
    rules_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Each minute: note every recording's size, and fold newly listed next episodes into its run."""
    from engine.dvr import DvrManager, patch_sidecar, read_sidecar
    from engine.rules import note_recorded
    from engine.schedule import load_schedule, remove_later

    stamp = time.time() if now is None else float(now)
    joined: List[Dict[str, Any]] = []
    for session in DvrManager.load_active_sessions(active_path):
        if not session.is_active() or not session.file_path:
            continue
        side = read_sidecar(session.file_path)
        if not side:
            continue
        fields: Dict[str, Any] = {"marks": note_size(side, stamp, session.get_file_size())}
        eps = list(side.get("episodes") or [])
        tune = str(side.get("queue_tune") or "")
        if eps and tune:
            last = max(eps, key=lambda e: int(e.get("start_unix") or 0))
            last_start = int(last.get("start_unix") or 0)
            more = follows(load_schedule(schedule_path), tune, last_start + int(last.get("duration_sec") or 0), last_start)
            if more:
                fields["episodes"] = eps + [episode_of(row) for row in more]
                fields["planned_end"] = max(int(side.get("planned_end") or 0), run_stop(more))
                for row in more:
                    remove_later(str(row.get("id") or ""), path=schedule_path)
                    note_recorded(str(row.get("rule_id") or ""), row.get("synopsis"), path=rules_path)
                joined.extend(more)
        patch_sidecar(session.file_path, **fields)
    return joined


def byte_at(marks: List[Tuple[float, int]], t: float) -> int:
    """Byte offset for an air time, straight-line between the minute notes."""
    if not marks:
        return 0
    if t <= marks[0][0]:
        return int(marks[0][1])
    for (t0, b0), (t1, b1) in zip(marks, marks[1:]):
        if t <= t1:
            if t1 <= t0:
                return int(b1)
            return int(b0 + (b1 - b0) * (t - t0) / (t1 - t0))
    return int(marks[-1][1])


def _align_down(n: int) -> int:
    n = max(0, int(n))
    return n - (n % TS_PACKET)


def _align_up(n: int, limit: int) -> int:
    n = max(0, int(n))
    up = n + (-n % TS_PACKET)
    return min(up, limit)


def plan_pieces(side: Dict[str, Any], size: int) -> List[Tuple[Dict[str, Any], int, int]]:
    """Each episode with its byte range. Episodes the run never reached are left out."""
    start = int(side.get("start") or 0)
    end = int(side.get("end") or 0) or start
    total = int(side.get("split_size") or size)
    marks = sorted(
        {(int(m[0]), int(m[1])) for m in (side.get("marks") or []) if isinstance(m, list) and len(m) == 2}
        | {(start, 0), (end, total)}
    )
    clean: List[Tuple[int, int]] = []
    for t, b in marks:
        if clean and b < clean[-1][1]:
            continue
        clean.append((t, min(b, total)))
    pieces = []
    for ep in sorted(side.get("episodes") or [], key=lambda e: int(e.get("start_unix") or 0)):
        a = max(start, int(ep.get("start_unix") or 0) - PAD_EARLY_SEC)
        b = min(end, int(ep.get("start_unix") or 0) + int(ep.get("duration_sec") or 0) + PAD_LATE_SEC)
        if b - a < 60:
            continue
        lo = _align_down(byte_at(clean, a))
        hi = _align_up(byte_at(clean, b), total)
        if hi - lo < TS_PACKET * 64:
            continue
        pieces.append((dict(ep, span=[a, b]), lo, hi))
    return pieces


def episode_filename(side: Dict[str, Any], ep: Dict[str, Any]) -> str:
    from engine.dvr import sanitize_filename

    when = datetime.fromtimestamp(int(ep.get("start_unix") or 0)).strftime("%Y%m%d_%H%M%S")
    channel = sanitize_filename(str(side.get("channel") or ""))
    station = sanitize_filename(str(side.get("station") or ""))
    title = sanitize_filename(str(ep.get("title") or side.get("title") or ""))
    return f"{channel}-{station}_{title}_{when}.ts"


def _copy_range(src: str, dest: str, lo: int, hi: int) -> None:
    tmp = f"{dest}.part"
    fd_out = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    try:
        with open(src, "rb") as fin:
            fd_in = fin.fileno()
            left = hi - lo
            offset = lo
            while left > 0:
                n = min(COPY_CHUNK, left)
                try:
                    done = os.copy_file_range(fd_in, fd_out, n, offset)
                except (AttributeError, OSError):
                    fin.seek(offset)
                    chunk = fin.read(n)
                    done = os.write(fd_out, chunk) if chunk else 0
                if done <= 0:
                    break
                offset += done
                left -= done
        os.fsync(fd_out)
    finally:
        os.close(fd_out)
    os.replace(tmp, dest)
    chmod_private_file(dest)


def _free_name(folder: str, name: str, mine: str) -> str:
    path = os.path.join(folder, name)
    if not os.path.exists(path) or os.path.realpath(path) == os.path.realpath(mine):
        return path
    root, ext = os.path.splitext(name)
    n = 2
    while os.path.exists(os.path.join(folder, f"{root}-{n}{ext}")):
        n += 1
    return os.path.join(folder, f"{root}-{n}{ext}")


def _episode_side(side: Dict[str, Any], ep: Dict[str, Any], source: str, lo: int, hi: int) -> Dict[str, Any]:
    keep = {k: side.get(k) for k in ("station", "channel", "tune_name", "service_id", "full_mux")}
    a, b = (ep.get("span") or [0, 0])[:2]
    keep.update({
        "title": ep.get("title") or side.get("title") or "",
        "synopsis": ep.get("synopsis") or "",
        "start": int(a),
        "end": int(b),
        "listed_start": int(ep.get("start_unix") or 0) or None,
        "byte_rate": round((hi - lo) / (b - a), 1) if b > a else None,
        "rule_id": ep.get("rule_id") or side.get("rule_id") or "",
        "status": "complete",
        "split_from": os.path.basename(source),
    })
    return keep


def in_use(path: str) -> bool:
    try:
        res = subprocess.run(["fuser", path], capture_output=True, timeout=2)
    except FileNotFoundError:
        return False
    except Exception:
        return True
    return res.returncode == 0


def split_recording(path: str) -> List[str]:
    """Cut a finished run into episode files. Safe to run again after a crash."""
    from engine.dvr import patch_sidecar, read_sidecar, sidecar_path, write_sidecar

    side = read_sidecar(path)
    if str(side.get("status") or "") != "complete" or len(side.get("episodes") or []) < 2:
        return []
    size = os.path.getsize(path)
    if "split_size" not in side:
        side = patch_sidecar(path, split_size=size)
    pieces = plan_pieces(side, size)
    folder = os.path.dirname(path)
    if len(pieces) < 2:
        only = pieces[0][0] if pieces else None
        named = {"title": only["title"], "synopsis": only.get("synopsis", ""), "rule_id": only.get("rule_id") or side.get("rule_id") or "",
                 "listed_start": int(only.get("start_unix") or 0) or None} if only else {}
        patch_sidecar(path, episodes=[], **named)
        return [path]
    made: List[str] = []
    for i in range(len(pieces) - 1, -1, -1):
        ep, lo, hi = pieces[i]
        dest = _free_name(folder, episode_filename(side, ep), path)
        meta = _episode_side(side, ep, path, lo, hi)
        if i == 0 and lo == 0:
            with open(path, "r+b") as f:
                f.truncate(min(hi, os.path.getsize(path)))
            if os.path.realpath(dest) != os.path.realpath(path):
                os.replace(path, dest)
                try:
                    os.remove(sidecar_path(path))
                except OSError:
                    pass
            write_sidecar(dest, meta)
            made.append(dest)
            break
        _copy_range(path, dest, lo, hi)
        write_sidecar(dest, meta)
        made.append(dest)
        if i == 0:
            os.remove(path)
            try:
                os.remove(sidecar_path(path))
            except OSError:
                pass
            break
        keep_to = max(p[2] for p in pieces[:i])
        patch_sidecar(path, episodes=[p[0] for p in pieces[:i]])
        with open(path, "r+b") as f:
            f.truncate(min(keep_to, os.path.getsize(path)))
    return list(reversed(made))


def waiting_splits(recordings_dir: str) -> List[str]:
    from engine.dvr import read_sidecar

    out = []
    try:
        entries = list(os.scandir(recordings_dir))
    except OSError:
        return []
    for entry in entries:
        if not entry.name.endswith(".ts") or not entry.is_file(follow_symlinks=False):
            continue
        side = read_sidecar(entry.path)
        if str(side.get("status") or "") == "complete" and len(side.get("episodes") or []) >= 2:
            out.append(entry.path)
    return sorted(out)


def split_waiting(recordings_dir: str) -> List[str]:
    """Split every finished run nobody has open."""
    made: List[str] = []
    for path in waiting_splits(recordings_dir):
        if in_use(path):
            continue
        made.extend(split_recording(path))
    return made


def finish_recordings(recordings_dir: str, min_bytes: int) -> List[str]:
    """Split finished runs, then mark ad breaks. One finisher at a time; returns files touched."""
    from engine.ads import mark_ads, waiting_marks

    touched: List[str] = []
    try:
        with state_lock(FINISH_LOCK_KEY, timeout=0):
            touched.extend(split_waiting(recordings_dir))
            for path in waiting_marks(recordings_dir, min_bytes):
                mark_ads(path)
                touched.append(path)
    except TimeoutError:
        return []
    return touched


def finish_waiting(recordings_dir: str, min_bytes: int) -> bool:
    from engine.ads import waiting_marks

    return bool(waiting_splits(recordings_dir) or waiting_marks(recordings_dir, min_bytes))
