#!/usr/bin/env python3
"""Pre-review check for the classes a security review keeps blocking.

One command, from the repo root:

    python3 scripts/pre_review.py

Exit 0 when every check passes. Exit 1 when any check fails. The text is a
pass/fail list in plain English. Point it at another checkout to review that
tree with these rules:

    python3 scripts/pre_review.py /path/to/other/checkout

What it looks for:

- A release snapshot that would ship agent files, developer setup, secrets,
  or a .env. publish() has to pass an allowlist into git archive. The
  allowlist lives in this file; widening engine/release.py is not enough.
- A subprocess that reads all of stdout or stderr, or a timeout that does
  not kill the process group. engine/procio.py is the one place that may
  hold the pipes, and it has to kill the group.
- A broadcast or binary parser that walks a count or length taken from the
  buffer without stopping at the bytes that are left, or that stacks parsed
  objects for every repeated section and only dedupes afterward.
- sudo, a package manager, or loginctl in a file an agent runs on its own:
  .cursor/environment.json, the scripts that file names, and githooks.
  GitHub Actions is not that set. The workflow calls scripts/dev-setup.sh
  on a CI runner on purpose.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from typing import Iterable, List, Optional, Sequence, Tuple

# Keep this in step with engine/release.py. tests/test_pre_review.py checks.
ALLOW_DIRS = (
    "assets/",
    "bin/",
    "engine/",
    "markets/",
    "player/",
    "plugin/",
    "systemd/",
)
ALLOW_FILES = frozenset({
    "CHANGELOG.md",
    "DESIGN.md",
    "HARDWARE_AND_TROUBLESHOOTING.md",
    "LICENSE",
    "README.md",
    "manifest.json",
})
_DENY = re.compile(
    r"^AGENTS\.md$|(^|/)\.cursor(/|$)|^\.github(/|$)|^scripts(/|$)"
    r"|^tests(/|$)|^githooks(/|$)|^skills(/|$)|^\.gitignore$"
    r"|^\.cursorignore$|(^|/)\.env($|\.)|(^|/)id_rsa($|\.)"
    r"|\.(pem|p12|key)$|(^|/)credentials([^/]|$)|(^|/)secrets?(/|$)"
    r"|dev-setup|(^|/)setup[^/]*\.sh$",
    re.IGNORECASE,
)
_PRIV = re.compile(
    r"\b(sudo|pkexec|doas|loginctl|apt-get|pacman|dnf|yum|zypper)\b"
    r"|\bapt\s+(install|update)\b"
)
_INVOKE = re.compile(
    r"(?:^|[;&|\n])\s*(?:bash|sh|source)\s+([^\s;&|\"']+\.sh)\b"
    r"|(?:^|[;&|\n])\s*\.\s+([^\s;&|\"']+\.sh)\b",
    re.MULTILINE,
)
_CAPTURE_FUNCS = {"run", "check_output", "check_call", "getoutput", "getstatusoutput"}
_PIPE_ATTRS = {"PIPE", "STDOUT"}


def main(argv: Sequence[str]) -> int:
    root = os.path.abspath(argv[1] if len(argv) > 1 else os.getcwd())
    if not os.path.isdir(os.path.join(root, "engine")):
        print(f"Pre-review check failed.\n  {root} has no engine/ directory.")
        return 1
    checks = [
        ("Parsers stop at the end of the buffer, and repeated sections do not pile up.", _parsers(root)),
        ("Captured command output is size-capped, and a timeout kills the process group.", _subprocesses(root)),
        ("The release snapshot stays on the allowlist, and automatic setup does not use privilege.", _payload(root)),
    ]
    failed = False
    print("Pre-review check")
    for title, problems in checks:
        if problems:
            failed = True
            print(f"  FAIL  {title}")
            for line in problems:
                print(f"        - {line}")
        else:
            print(f"  PASS  {title}")
    if failed:
        print("Pre-review check failed.")
        return 1
    print("Pre-review check passed.")
    return 0


def _allowed(path: str) -> bool:
    name = path.replace("\\", "/").lstrip("./")
    if not name or _DENY.search(name):
        return False
    if name in ALLOW_FILES:
        return True
    return any(name.startswith(prefix) for prefix in ALLOW_DIRS)


def _py_files(root: str) -> Iterable[str]:
    for base in ("engine", "player", "bin"):
        start = os.path.join(root, base)
        if not os.path.isdir(start):
            continue
        for dirpath, _dirs, files in os.walk(start):
            for name in files:
                path = os.path.join(dirpath, name)
                if name.endswith(".py") or _python_script(path):
                    yield path


def _python_script(path: str) -> bool:
    try:
        with open(path, "rb") as handle:
            head = handle.read(80)
    except OSError:
        return False
    return head.startswith(b"#!") and b"python" in head


def _parse(path: str) -> Optional[ast.AST]:
    try:
        with open(path, encoding="utf-8") as handle:
            return ast.parse(handle.read(), filename=path)
    except (OSError, SyntaxError):
        return None


def _rel(root: str, path: str) -> str:
    return os.path.relpath(path, root)


def _parsers(root: str) -> List[str]:
    problems: List[str] = []
    for path in sorted(_py_files(root)):
        tree = _parse(path)
        if tree is None:
            continue
        rel = _rel(root, path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name in {"u", "raw"}:
                        hit = _partial_read(item)
                        if hit:
                            problems.append(
                                f"{rel}:{hit} {node.name}.{item.name} returns a value when the buffer runs out, "
                                "so a short section is read as zeros."
                            )
            if isinstance(node, ast.FunctionDef):
                counts = _declared_counts(node)
                for loop in (n for n in ast.walk(node) if isinstance(n, ast.For)):
                    name = _range_count(loop, counts)
                    if name and not _count_loop_stops(loop):
                        problems.append(
                            f"{rel}:{loop.lineno} {node.name} loops on {name} from the buffer "
                            "without stopping when the bytes run out."
                        )
                for loop in (n for n in ast.walk(node) if isinstance(n, ast.For)):
                    if _section_loop(loop) and _retains_without_bound(loop):
                        problems.append(
                            f"{rel}:{loop.lineno} {node.name} keeps every parsed object from repeated sections "
                            "before it dedupes or caps them."
                        )
    return problems


def _partial_read(fn: ast.FunctionDef) -> int:
    """Line of a short-buffer branch that returns a filler value, or 0."""
    if "data" not in {n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)}:
        return 0
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        if not _mentions_length(node.test):
            continue
        returns = [n for n in node.body if isinstance(n, ast.Return) and n.value is not None]
        raises = [n for n in node.body if isinstance(n, ast.Raise)]
        if returns and not raises:
            return node.lineno
    return 0


def _mentions_length(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name) and child.func.id == "len":
            return True
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) and child.func.attr == "remaining":
            return True
    return False


def _reads_buffer(node: Optional[ast.AST]) -> bool:
    if node is None:
        return False
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in {"u", "raw", "unpack", "unpack_from"}:
            return True
        return any(_reads_buffer(arg) for arg in node.args) or any(_reads_buffer(k.value) for k in node.keywords)
    if isinstance(node, ast.Subscript):
        return _reads_buffer(node.value)
    if isinstance(node, ast.BinOp):
        return _reads_buffer(node.left) or _reads_buffer(node.right)
    if isinstance(node, ast.UnaryOp):
        return _reads_buffer(node.operand)
    return False


def _declared_counts(fn: ast.FunctionDef) -> set:
    names = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            if _reads_buffer(node.value):
                names.add(node.targets[0].id)
    return names


def _range_count(loop: ast.For, counts: set) -> str:
    call = loop.iter
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name) or call.func.id != "range":
        return ""
    if not call.args:
        return ""
    arg = call.args[0]
    if isinstance(arg, ast.Name) and arg.id in counts:
        return arg.id
    if _reads_buffer(arg):
        return "a declared count"
    return ""


def _count_loop_stops(loop: ast.For) -> bool:
    has_break = False
    has_guard = False
    stack = list(loop.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.For, ast.While, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(node, ast.Break):
            has_break = True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "remaining":
            has_guard = True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "len":
            has_guard = True
        if isinstance(node, ast.ExceptHandler) and any(isinstance(x, (ast.Break, ast.Return)) for x in ast.walk(node)):
            has_guard = True
            has_break = True
        stack.extend(ast.iter_child_nodes(node))
    return has_break and has_guard


def _section_loop(loop: ast.For) -> bool:
    return isinstance(loop.target, ast.Name) and loop.target.id == "section"


def _retains_without_bound(loop: ast.For) -> bool:
    grows = False
    capped = False
    deduped = False
    for node in ast.walk(loop):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"append", "extend"}:
            grows = True
        if isinstance(node, ast.Compare):
            if isinstance(node.left, ast.Call) and isinstance(node.left.func, ast.Name) and node.left.func.id == "len":
                capped = True
            if any(isinstance(op, (ast.In, ast.NotIn)) for op in node.ops):
                deduped = True
    return grows and not (capped and deduped)


def _subprocesses(root: str) -> List[str]:
    problems: List[str] = []
    helper = os.path.join(root, "engine", "procio.py")
    if os.path.isfile(helper):
        text = open(helper, encoding="utf-8").read()
        if "killpg" not in text or "start_new_session" not in text:
            problems.append("engine/procio.py does not start a new session and kill the process group.")
        tree = _parse(helper)
        if tree is not None:
            for hit in _capture_calls(tree):
                if hit[1] == "communicate":
                    problems.append(f"engine/procio.py:{hit[0]} reads the pipes with communicate().")
    for path in sorted(_py_files(root)):
        if os.path.basename(path) == "procio.py":
            continue
        tree = _parse(path)
        if tree is None:
            continue
        rel = _rel(root, path)
        for lineno, kind in _capture_calls(tree):
            if kind == "timeout":
                problems.append(
                    f"{rel}:{lineno} sets a subprocess timeout without killing the process group."
                )
            elif kind == "communicate":
                problems.append(f"{rel}:{lineno} reads a pipe with communicate() and no byte cap.")
            else:
                problems.append(
                    f"{rel}:{lineno} reads command output with no byte cap ({kind})."
                )
    return problems


def _capture_calls(tree: ast.AST) -> List[Tuple[int, str]]:
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "communicate":
            found.append((node.lineno, "communicate"))
            continue
        name = ""
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "subprocess":
            name = func.attr
        elif isinstance(func, ast.Name) and func.id in _CAPTURE_FUNCS:
            name = func.id
        if not name:
            continue
        if name in {"check_output", "getoutput", "getstatusoutput"}:
            found.append((node.lineno, name))
            continue
        if name == "Popen":
            if _piped(node) or _has_timeout(node):
                found.append((node.lineno, "Popen pipe" if _piped(node) else "timeout"))
            continue
        if name in {"run", "check_call"}:
            if _piped(node) or _capture_output(node):
                found.append((node.lineno, "capture_output" if _capture_output(node) else "PIPE"))
            elif _has_timeout(node):
                found.append((node.lineno, "timeout"))
    return found


def _keyword(node: ast.Call, name: str) -> Optional[ast.AST]:
    for item in node.keywords:
        if item.arg == name:
            return item.value
    return None


def _has_timeout(node: ast.Call) -> bool:
    return _keyword(node, "timeout") is not None


def _capture_output(node: ast.Call) -> bool:
    value = _keyword(node, "capture_output")
    return isinstance(value, ast.Constant) and value.value is True


def _piped(node: ast.Call) -> bool:
    for name in ("stdout", "stderr"):
        value = _keyword(node, name)
        if isinstance(value, ast.Attribute) and value.attr in _PIPE_ATTRS:
            return True
    return False


def _payload(root: str) -> List[str]:
    problems: List[str] = []
    problems.extend(_snapshot(root))
    problems.extend(_privilege(root))
    return problems


def _snapshot(root: str) -> List[str]:
    release = os.path.join(root, "engine", "release.py")
    if not os.path.isfile(release):
        return ["engine/release.py is missing, so the snapshot has no allowlist."]
    try:
        source = open(release, encoding="utf-8").read()
    except OSError as exc:
        return [f"Could not read engine/release.py ({exc})."]
    try:
        tracked = _tracked(root)
    except OSError as exc:
        return [f"Could not list tracked files ({exc})."]
    if _publish_filters(source):
        try:
            shipped = _shipped_by_release(root)
        except Exception as exc:
            return [f"publish() claims to filter the snapshot, but listing it failed ({exc})."]
    else:
        shipped = tracked
    outside = [path for path in shipped if not _allowed(path)]
    if not outside and _publish_filters(source):
        return []
    problems = []
    if not _publish_filters(source):
        problems.append(
            "publish() archives all of HEAD. Agent notes, Cursor setup, and developer scripts are in that snapshot."
        )
    named = [path for path in outside if path in {"AGENTS.md", ".cursor/environment.json"} or path.startswith(".cursor/") or path.startswith("scripts/")]
    secrets = [path for path in outside if ".env" in path or path.endswith((".pem", ".key", ".p12")) or "secret" in path.lower()]
    shown = []
    for path in named + secrets:
        if path not in shown:
            shown.append(path)
    for path in outside:
        if path not in shown:
            shown.append(path)
        if len(shown) >= 8:
            break
    if shown:
        extra = len(outside) - len(shown)
        tail = f" and {extra} more" if extra > 0 else ""
        problems.append("The snapshot would include " + ", ".join(shown) + tail + ".")
    return problems


def _publish_filters(source: str) -> bool:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "publish":
            continue
        fed = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Assign) and len(sub.targets) == 1 and isinstance(sub.targets[0], ast.Name):
                call = sub.value
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "snapshot_paths":
                    fed.add(sub.targets[0].id)
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            constants = [arg.value for arg in sub.args if isinstance(arg, ast.Constant)]
            if "archive" not in constants:
                continue
            for arg in sub.args:
                if isinstance(arg, ast.Starred) and isinstance(arg.value, ast.Name) and arg.value.id in fed:
                    return True
    return False


def _tracked(root: str) -> List[str]:
    try:
        res = subprocess.run(
            ["git", "-c", "safe.directory=*", "-C", root, "ls-files", "-z"],
            check=True, capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        err = (exc.stderr or b"").decode("utf-8", "replace").strip()
        raise OSError(err or f"git ls-files exited {exc.returncode}") from exc
    return [part.decode("utf-8", "surrogateescape") for part in res.stdout.split(b"\0") if part]


def _shipped_by_release(root: str) -> List[str]:
    import importlib.util

    path = os.path.join(root, "engine", "release.py")
    # release.py imports engine.procio. Load this checkout, not whatever
    # engine package is already in the process.
    name = "yagi_release_under_review"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load engine/release.py")
    module = importlib.util.module_from_spec(spec)
    inserted = False
    if root not in sys.path:
        sys.path.insert(0, root)
        inserted = True
    try:
        spec.loader.exec_module(module)
    finally:
        if inserted and root in sys.path:
            sys.path.remove(root)
    return list(module.snapshot_paths(root))


def _privilege(root: str) -> List[str]:
    problems = []
    for path in _auto_files(root):
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        hits = sorted({match.group(0) for match in _PRIV.finditer(text)})
        if not hits:
            continue
        rel = _rel(root, path)
        kinds = ", ".join(hits)
        problems.append(f"{rel} runs on its own and uses {kinds}.")
    return problems


def _auto_files(root: str) -> List[str]:
    """Files an agent or git runs without a person asking for a privileged step."""
    seeds = []
    cursor = os.path.join(root, ".cursor")
    if os.path.isdir(cursor):
        for dirpath, _dirs, files in os.walk(cursor):
            for name in files:
                if name.endswith((".json", ".sh", ".yml", ".yaml")):
                    seeds.append(os.path.join(dirpath, name))
    for hooks in ("githooks", ".githooks"):
        folder = os.path.join(root, hooks)
        if os.path.isdir(folder):
            for dirpath, _dirs, files in os.walk(folder):
                for name in files:
                    seeds.append(os.path.join(dirpath, name))
    seen = set()
    ordered = []

    def add(path: str) -> None:
        real = os.path.realpath(path)
        if real in seen or not real.startswith(os.path.realpath(root) + os.sep):
            return
        if not os.path.isfile(real):
            return
        seen.add(real)
        ordered.append(real)
        _follow_scripts(root, real, add)

    for path in seeds:
        add(path)
    return ordered


def _follow_scripts(root: str, path: str, add) -> None:
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return
    commands = []
    if path.endswith(".json"):
        try:
            commands.extend(_strings(json.loads(text)))
        except json.JSONDecodeError:
            commands.append(text)
    else:
        commands.append(text)
    for command in commands:
        for match in _INVOKE.finditer(command):
            rel = next(group for group in match.groups() if group)
            rel = rel.strip("\"'")
            candidate = rel if os.path.isabs(rel) else os.path.join(root, rel)
            add(candidate)


def _strings(value) -> List[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out = []
        for item in value.values():
            out.extend(_strings(item))
        return out
    if isinstance(value, list):
        out = []
        for item in value:
            out.extend(_strings(item))
        return out
    return []


if __name__ == "__main__":
    sys.exit(main(sys.argv))
