"""Run a child and keep its output, and its descendants, inside a bound.

subprocess.run(capture_output=True) reads until the pipe closes, then a
timeout kills only the process it started. A shell that still has a writer
in the background keeps the pipe open and keeps the bytes coming. Callers
pass a byte cap. This reads at most that many bytes plus one, so it can see
that the child had more, and then signals the whole process group.
"""

from __future__ import annotations

import os
import select
import signal
import subprocess
import time
from typing import Mapping, Optional, Sequence


def capture(
    argv: Sequence[str],
    *,
    max_bytes: int,
    timeout: float,
    text: bool = False,
    errors: str = "strict",
    env: Optional[Mapping[str, str]] = None,
    pass_fds: Sequence[int] = (),
    check: bool = False,
) -> subprocess.CompletedProcess:
    """Stdout and stderr each stop at max_bytes. timeout kills the group."""
    limit = max(0, int(max_bytes))
    # One extra byte shows the stream did not end inside the cap.
    stop_at = limit + 1
    proc = subprocess.Popen(
        list(argv),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        start_new_session=True,
        env=None if env is None else dict(env),
        pass_fds=tuple(pass_fds),
    )
    try:
        proc._yagi_sid = os.getsid(proc.pid)  # type: ignore[attr-defined]
    except OSError:
        proc._yagi_sid = None  # type: ignore[attr-defined]
    stdout = bytearray()
    stderr = bytearray()
    deadline = time.monotonic() + max(0.0, float(timeout))
    timed_out = False
    try:
        pipes = [proc.stdout, proc.stderr]
        while pipes:
            if time.monotonic() >= deadline:
                timed_out = True
                break
            if len(stdout) >= stop_at or len(stderr) >= stop_at:
                break
            wait = min(0.05, max(0.0, deadline - time.monotonic()))
            readable, _, _ = select.select(pipes, [], [], wait)
            if not readable:
                if proc.poll() is not None:
                    # The child is gone. Drain whatever select has not reported yet.
                    _drain(proc.stdout, stdout, stop_at)
                    _drain(proc.stderr, stderr, stop_at)
                    break
                continue
            for pipe in readable:
                buf = stdout if pipe is proc.stdout else stderr
                if len(buf) >= stop_at:
                    if pipe in pipes:
                        pipes.remove(pipe)
                    continue
                try:
                    chunk = os.read(pipe.fileno(), 65536)
                except OSError:
                    chunk = b""
                if not chunk:
                    if pipe in pipes:
                        pipes.remove(pipe)
                    continue
                room = stop_at - len(buf)
                if room > 0:
                    buf.extend(chunk[:room])
                if len(buf) >= stop_at and pipe in pipes:
                    pipes.remove(pipe)
        overflow = len(stdout) > limit or len(stderr) > limit
        # A child that already exited keeps its status. Kill only sweeps
        # descendants, or a child that is still producing bytes.
        if not timed_out and not overflow and proc.poll() is None:
            try:
                proc.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                pass
    finally:
        _kill_group(proc)
        for pipe in (proc.stdout, proc.stderr):
            if pipe is not None:
                try:
                    pipe.close()
                except OSError:
                    pass
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass

    out = bytes(stdout[:limit])
    err = bytes(stderr[:limit])
    if text:
        out = out.decode("utf-8", errors)
        err = err.decode("utf-8", errors)
    if timed_out:
        raise subprocess.TimeoutExpired(list(argv), timeout, output=out, stderr=err)
    result = subprocess.CompletedProcess(list(argv), proc.returncode if proc.returncode is not None else -1, out, err)
    if check and result.returncode:
        raise subprocess.CalledProcessError(result.returncode, list(argv), out, err)
    return result


def _drain(pipe, buf: bytearray, stop_at: int) -> None:
    if pipe is None or len(buf) >= stop_at:
        return
    while len(buf) < stop_at:
        try:
            chunk = os.read(pipe.fileno(), 65536)
        except OSError:
            return
        if not chunk:
            return
        room = stop_at - len(buf)
        buf.extend(chunk[:room])


def _killpg_if_not_ours(pgid: int) -> None:
    """Signal one process group, and never the caller's group.

    Signaling our own group is SIGKILL for the test runner and the CI job.
    """
    if pgid <= 1 or pgid == os.getpgrp():
        return
    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        pass


def _kill_group(proc: subprocess.Popen) -> None:
    """Stop this child and every process it started.

    Descendants are stopped by pid first, so a background job that left
    its leader's group still dies. Other groups in the child's session
    go through _killpg_if_not_ours. A child that stayed in our session
    is stopped by pid only.
    """
    pid = proc.pid
    if not pid or pid <= 1 or pid == os.getpid():
        return
    my_sid = os.getsid(0)
    sid = getattr(proc, "_yagi_sid", None)
    if not sid:
        try:
            sid = os.getsid(pid)
        except OSError:
            sid = None
    for child in _descendants(pid):
        if child <= 1 or child == os.getpid():
            continue
        try:
            os.kill(child, signal.SIGKILL)
        except OSError:
            pass
    if sid and sid > 1 and sid != my_sid:
        for _pid, _ppid, pgrp, session in _proc_ids():
            if session == sid:
                _killpg_if_not_ours(pgrp)
        for other, _ppid, pgrp, session in _proc_ids():
            if session != sid or other <= 1 or other == os.getpid():
                continue
            if pgrp == os.getpgrp():
                continue
            try:
                os.kill(other, signal.SIGKILL)
            except OSError:
                pass
    _kill_pid(proc)


def _kill_pid(proc: subprocess.Popen) -> None:
    try:
        proc.kill()
    except OSError:
        pass


def _descendants(pid: int) -> list:
    found = []
    for child in _children(pid):
        found.append(child)
        found.extend(_descendants(child))
    return found


def _children(pid: int) -> list:
    found = []
    for entry in _proc_ids():
        if entry[1] == pid:
            found.append(entry[0])
    return found


def _proc_ids():
    """pid, ppid, pgrp, session for each live process."""
    rows = []
    try:
        entries = list(os.scandir("/proc"))
    except OSError:
        return rows
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            with open(f"/proc/{entry.name}/stat", encoding="utf-8") as handle:
                stat = handle.read()
        except OSError:
            continue
        end = stat.rfind(")")
        if end < 0:
            continue
        fields = stat[end + 2:].split()
        # state ppid pgrp session
        if len(fields) < 4:
            continue
        try:
            rows.append((int(entry.name), int(fields[1]), int(fields[2]), int(fields[3])))
        except ValueError:
            continue
    return rows
