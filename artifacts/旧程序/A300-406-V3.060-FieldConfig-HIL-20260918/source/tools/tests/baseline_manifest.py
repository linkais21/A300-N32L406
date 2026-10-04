#!/usr/bin/env python3
"""Capture build baseline metadata and exercise the release guard contract."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from release_guard import scan  # noqa: E402


def file_size(path: Path):
    return path.stat().st_size if path.is_file() else None


def git_revision(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=False,
        capture_output=True, text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def collect(root: Path, elf: Path, map_file: Path):
    return {
        "repository": str(root),
        "git_revision": git_revision(root),
        "elf": {"path": str(elf), "bytes": file_size(elf)},
        "map": {"path": str(map_file), "bytes": file_size(map_file)},
        "build_command": "make all",
    }


def self_test():
    # This fixture is intentionally legacy: it proves the guard fails closed.
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        legacy = root / "include" / "fixture.h"
        legacy.parent.mkdir()
        legacy.write_text('#define OLD "T663B"\n', encoding="utf-8")
        assert scan(root), "legacy release text must be rejected"
        legacy.write_text('#define CURRENT "A300_406"\n', encoding="utf-8")
        assert not scan(root), "current release text must pass"
    print("baseline_manifest: PASS (release guard contract)")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elf", type=Path, default=ROOT / "build" / "a300_firmware.elf")
    parser.add_argument("--map", dest="map_file", type=Path, default=ROOT / "build" / "a300_firmware.map")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    self_test()
    if args.self_test:
        return 0
    record = collect(ROOT, args.elf.resolve(), args.map_file.resolve())
    encoded = json.dumps(record, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
