#!/usr/bin/env python3
"""Reject legacy product/version identifiers in release-controlled files."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

FORBIDDEN = ("T663B", "A300_202511", "V1.274")
TARGET_VERSION = "T360-A300_406_20260823000000,V3.000"
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
    "gen_version.ps1",
)

IDENTITY_CONSUMERS = (
    "src/main.c", "src/jt808.c", "src/jt808_params.c", "src/terminal_identity.c",
)
SEVEN_BYTE_LITERAL = re.compile(r'"([A-Za-z0-9]{7})"')


def strip_c_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/|//[^\r\n]*", "", text, flags=re.DOTALL)


def fixed_identity_findings(text: str):
    """Return seven-byte alphanumeric literals from an identity consumer."""
    return [match.group(1) for match in SEVEN_BYTE_LITERAL.finditer(strip_c_comments(text))]


def generated_version_is_target(text: str) -> bool:
    """Require the generator's release version source to be the approved target."""
    match = re.search(r'(?m)^\s*\$FW_VERSION\s*=\s*"([^"]+)"\s*$', text)
    return match is not None and match.group(1) == TARGET_VERSION


def c_define_is_target(text: str, name: str) -> bool:
    match = re.search(rf'(?m)^\s*#define\s+{re.escape(name)}\s+"([^"]+)"\s*$', text)
    return match is not None and match.group(1) == TARGET_VERSION


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
        relative = path.relative_to(root).as_posix()
        if relative in IDENTITY_CONSUMERS:
            for terminal_id in fixed_identity_findings("\n".join(lines)):
                findings.append((path, 0, "<fixed-terminal-id>", terminal_id))
        if path.name.casefold() == "gen_version.ps1" and not generated_version_is_target("\n".join(lines)):
            findings.append((path, 0, "<target-version>", f"expected {TARGET_VERSION}"))
        if relative == "include/config.h" and not c_define_is_target("\n".join(lines), "FW_VERSION_STR"):
            findings.append((path, 0, "<target-version>", f"FW_VERSION_STR must be {TARGET_VERSION}"))
        if relative == "include/build_version.h" and not c_define_is_target("\n".join(lines), "FW_FULL_VERSION"):
            findings.append((path, 0, "<target-version>", f"FW_FULL_VERSION must be {TARGET_VERSION}"))
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
