#!/usr/bin/env python3
"""Reject high-stack generic libc parsers from the linked application."""

from pathlib import Path
import re
import sys


FORBIDDEN = ("sscanf", "atof", "strtod")


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: libc_parser_guard.py <application.map>")
        return 2
    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"libc-parser-guard: missing map: {path}")
        return 1
    text = path.read_text(encoding="utf-8", errors="replace")
    failed = False
    for symbol in FORBIDDEN:
        # Only an allocated symbol with a non-zero address is live. Archive
        # members listed at address zero were discarded by --gc-sections.
        pattern = rf"^\s+0x(?!0{{8,16}})[0-9a-fA-F]+\s+{re.escape(symbol)}\s*$"
        if re.search(pattern, text, re.MULTILINE):
            print(f"libc-parser-guard: FAIL live symbol {symbol}")
            failed = True
        else:
            print(f"libc-parser-guard: {symbol} absent")
    if failed:
        return 1
    print("libc-parser-guard: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
