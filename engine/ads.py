"""Find ad breaks in a finished recording. The player jumps over them; the file is never cut.

Comskip is used when it is installed. Without it, ffmpeg finds the black,
silent frames stations put between spots. Three or more of those, spaced like
15- and 30-second ads, are a break. A lone spot is left alone.
"""

import math
import os
import re
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Tuple

MIN_BREAK_SEC = 25
MAX_BREAK_SEC = 7 * 60
MAX_SPOT_SEC = 125
MIN_SPOT_SEC = 9
SPOT_STEP_SEC = 5
SPOT_SLACK_SEC = 1.5
SAME_CUT_SEC = 2.0
DETECT_TIMEOUT_SEC = 3 * 3600

_BLACK = re.compile(r"black_start:\s*([\d.]+)\s+black_end:\s*([\d.]+)")
_SIL_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SIL_END = re.compile(r"silence_end:\s*(-?[\d.]+)")


def comskip_path() -> Optional[str]:
    return shutil.which("comskip") or (
        os.path.expanduser("~/.local/bin/comskip") if os.access(os.path.expanduser("~/.local/bin/comskip"), os.X_OK) else None
    )


def parse_detect_log(text: str) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]]]:
    blacks: List[Tuple[float, float]] = []
    silences: List[Tuple[float, float]] = []
    open_at: Optional[float] = None
    for line in text.splitlines():
        m = _BLACK.search(line)
        if m:
            blacks.append((float(m.group(1)), float(m.group(2))))
            continue
        m = _SIL_START.search(line)
        if m:
            open_at = max(0.0, float(m.group(1)))
            continue
        m = _SIL_END.search(line)
        if m and open_at is not None:
            silences.append((open_at, float(m.group(1))))
            open_at = None
    return blacks, silences


def _spot_like(gap: float) -> bool:
    return gap >= MIN_SPOT_SEC and abs(gap - SPOT_STEP_SEC * round(gap / SPOT_STEP_SEC)) <= SPOT_SLACK_SEC


def breaks_from(blacks: List[Tuple[float, float]], silences: List[Tuple[float, float]]) -> List[List[float]]:
    """Ad breaks from black frames that land on silence."""
    quiet = [
        (b0 + b1) / 2 for b0, b1 in blacks
        if any(s0 - 0.5 <= b1 and s1 + 0.5 >= b0 for s0, s1 in silences)
    ]
    cuts: List[float] = []
    for t in sorted(quiet):
        if cuts and t - cuts[-1] < SAME_CUT_SEC:
            continue
        cuts.append(t)
    groups: List[List[float]] = []
    for t in cuts:
        if groups and t - groups[-1][-1] <= MAX_SPOT_SEC:
            groups[-1].append(t)
        else:
            groups.append([t])
    out: List[List[float]] = []
    for g in groups:
        if len(g) < 3:
            continue
        gaps = [b - a for a, b in zip(g, g[1:])]
        spots = sum(1 for gap in gaps if _spot_like(gap))
        span = g[-1] - g[0]
        if spots >= max(2, math.ceil(0.6 * len(gaps))) and MIN_BREAK_SEC <= span <= MAX_BREAK_SEC:
            out.append([round(g[0], 2), round(g[-1], 2)])
    return out


def _maps(side: Dict[str, Any]) -> List[str]:
    try:
        sid = int(side.get("service_id") or 0)
    except (TypeError, ValueError):
        sid = 0
    if side.get("full_mux") and sid > 0:
        return ["-map", f"0:p:{sid}:v:0?", "-map", f"0:p:{sid}:a:0?"]
    return ["-map", "0:v:0?", "-map", "0:a:0?"]


def ffmpeg_ads(path: str, side: Dict[str, Any]) -> List[List[float]]:
    cmd = [
        "nice", "-n", "19", "ffmpeg", "-hide_banner", "-nostats", "-nostdin", "-i", path,
        *_maps(side),
        "-vf", "scale=192:-2,blackdetect=d=0.1:pic_th=0.90:pix_th=0.12",
        "-af", "silencedetect=noise=-50dB:d=0.1",
        "-f", "null", "-",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=DETECT_TIMEOUT_SEC)
    blacks, silences = parse_detect_log(res.stderr)
    return breaks_from(blacks, silences)


def parse_edl(text: str) -> List[List[float]]:
    out = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            a, b = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        if b > a:
            out.append([round(a, 2), round(b, 2)])
    return out


def _with_program_table(path: str, side: Dict[str, Any], folder: str) -> Optional[str]:
    """A copy with a PMT, or None. mpv's one-station dump has none, and Comskip then decodes one frame."""
    from engine.dvr import KEEP_FREE_GIB

    try:
        if shutil.disk_usage(folder).free - os.path.getsize(path) < KEEP_FREE_GIB * 1024 ** 3:
            return None
    except OSError:
        return None
    dest = os.path.join(folder, "source.ts")
    res = subprocess.run(
        ["nice", "-n", "19", "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-i", path,
         *_maps(side), "-c", "copy", "-f", "mpegts", dest],
        capture_output=True, timeout=DETECT_TIMEOUT_SEC,
    )
    return dest if res.returncode == 0 and os.path.isfile(dest) else None


def comskip_ads(exe: str, path: str, side: Optional[Dict[str, Any]] = None) -> List[List[float]]:
    # The copy sits beside the recording, not in /tmp, which is RAM here. Only one
    # finisher runs at a time, so any copy already there was left by a killed one.
    folder = os.path.dirname(os.path.abspath(path))
    for entry in os.scandir(folder):
        if entry.name.startswith(".comskip-") and entry.is_dir(follow_symlinks=False):
            shutil.rmtree(entry.path, ignore_errors=True)
    with tempfile.TemporaryDirectory(prefix=".comskip-", dir=folder) as out:
        source = _with_program_table(path, side or {}, out) or path
        ini = os.path.join(out, "comskip.ini")
        with open(ini, "w", encoding="utf-8") as f:
            f.write("output_edl=1\noutput_txt=0\noutput_default=0\nverbose=0\n")
        subprocess.run(
            ["nice", "-n", "19", exe, f"--ini={ini}", f"--output={out}", "--quiet", source],
            capture_output=True, timeout=DETECT_TIMEOUT_SEC,
        )
        edl = os.path.join(out, os.path.splitext(os.path.basename(source))[0] + ".edl")
        try:
            with open(edl, encoding="utf-8") as f:
                return parse_edl(f.read())
        except OSError:
            return []


def media_seconds(path: str) -> float:
    try:
        res = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=60,
        )
        return float(res.stdout.strip() or 0)
    except (OSError, subprocess.SubprocessError, ValueError):
        return 0.0


def believable(breaks: List[List[float]], seconds: float) -> bool:
    """Comskip marks a short clip with no logo as one long ad. Skipping that would skip the show."""
    marked = sum(b - a for a, b in breaks)
    return not (seconds > 0 and marked > seconds / 2)


def find_ads(path: str, side: Dict[str, Any]) -> Tuple[List[List[float]], str]:
    exe = comskip_path()
    if exe:
        # A game's halftime reads as one long break. Drop that one, keep the rest.
        breaks = [span for span in comskip_ads(exe, path, side) if span[1] - span[0] <= MAX_BREAK_SEC]
        if breaks and believable(breaks, media_seconds(path)):
            return breaks, "comskip"
        why = "found no breaks" if not breaks else "marked most of it"
        print(f"Comskip {why} in {os.path.basename(path)}; using ffmpeg.", flush=True)
    return ffmpeg_ads(path, side), "ffmpeg"


def waiting_marks(recordings_dir: str, min_bytes: int) -> List[str]:
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
        if (
            str(side.get("status") or "") == "complete"
            and "ads" not in side
            and len(side.get("episodes") or []) < 2
            and entry.stat().st_size >= min_bytes
        ):
            out.append(entry.path)
    return sorted(out)


def mark_ads(path: str) -> List[List[float]]:
    from engine.dvr import patch_sidecar, read_sidecar

    side = read_sidecar(path)
    try:
        ads, by = find_ads(path, side)
    except (OSError, subprocess.SubprocessError):
        ads, by = [], "failed"
    if os.path.exists(path):
        patch_sidecar(path, ads=ads, ads_by=by)
    return ads
