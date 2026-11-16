#!/usr/bin/env python3
"""Check that a pushed tag matches the version in manifest.json.

The release workflow runs this when a v* tag is pushed. This script does
not create a tag and does not publish a release. Pass --notes to print the
changelog section for the manifest version.
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def manifest_version() -> str:
    with open(os.path.join(ROOT, "manifest.json"), encoding="utf-8") as handle:
        version = json.load(handle)["version"]
    if not isinstance(version, str) or not version:
        raise SystemExit("manifest.json has no version string.")
    return version


def changelog_notes(version: str) -> str:
    path = os.path.join(ROOT, "CHANGELOG.md")
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except OSError:
        return f"Yagi {version}"
    start = None
    for index, line in enumerate(lines):
        if line.startswith("## ") and line[3:].strip() == version:
            start = index + 1
            break
    if start is None:
        return f"Yagi {version}"
    body = []
    for line in lines[start:]:
        if line.startswith("## "):
            break
        body.append(line)
    text = "\n".join(body).strip()
    return text or f"Yagi {version}"


def main(argv: list[str]) -> int:
    version = manifest_version()
    if "--notes" in argv:
        print(changelog_notes(version))
        return 0
    ref = argv[1] if len(argv) > 1 else os.environ.get("GITHUB_REF", "")
    tag = ref.rsplit("/", 1)[-1] if ref.startswith("refs/tags/") else ref
    expect = "v" + version
    if tag != expect:
        shown = tag or "(none)"
        print(f"Tag {shown} does not match manifest.json version {version} ({expect}).")
        return 1
    print(f"{tag} matches manifest.json ({version}).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
