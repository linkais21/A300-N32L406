#!/usr/bin/env python3
"""Reject legacy product/version identifiers in release-controlled files."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

FORBIDDEN = ("T663B", "A300_202511", "V1.274")
DEFAULT_PATHS = (
    "src",
    "include",
    "ldscript",
    "bootloader",
    "firmware",
    "manifest.json",
    "manifest.yaml",
    "manifest.yml",
    "packaging",
)


def iter_release_files(root: Path, paths: tuple[str, ...] = DEFAULT_PATHS):
    """Yield existing text files under the configured release paths."""
    seen: set[Path] = set()
    for relative in paths:
        path = root / relative
        candidates = path.rglob("*") if path.is_dir() else (path,)
        for candidate in candidates:
            if not candidate.is_file() or candidate in seen:
                continue
            seen.add(candidate)
            yield candidate


def scan(root: Path, paths: tuple[str, ...] = DEFAULT_PATHS):
    """Return (file, line, token, text) tuples for forbidden matches."""
    findings = []
    patterns = [(token, re.compile(re.escape(token), re.IGNORECASE)) for token in FORBIDDEN]
    for path in iter_release_files(root, paths):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            findings.append((path, 0, "<read-error>", str(exc)))
            continue
        for number, line in enumerate(lines, 1):
            for token, pattern in patterns:
                if pattern.search(line):
                    findings.append((path, number, token, line.strip()))
    return findings


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--path", action="append", dest="paths", help="release path (repeatable)")
    args = parser.parse_args(argv)
    paths = tuple(args.paths) if args.paths else DEFAULT_PATHS
    findings = scan(args.root.resolve(), paths)
    if findings:
        for path, line, token, text in findings:
            print(f"release-guard: {path}:{line}: forbidden {token}: {text}", file=sys.stderr)
        print(f"release-guard: FAIL ({len(findings)} match(es))", file=sys.stderr)
        return 1
    print("release-guard: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
