#!/usr/bin/env python3
"""Build the unsigned A300 OTA transport image signed by the platform."""

from __future__ import annotations

import argparse
from pathlib import Path
import struct
import zlib


HEADER = struct.Struct("<IIIII12s")
MAGIC = 0xA300B007
PRODUCT_ID = 0x41333030
MAX_BODY_SIZE = 106496


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--version-code", required=True, type=int)
    args = parser.parse_args()
    if not 0 < args.version_code <= 0xFFFFFFFF:
        parser.error("version-code must be a positive uint32")
    body = args.input.read_bytes()
    if not 8 <= len(body) <= MAX_BODY_SIZE:
        parser.error("App body must be 8..106496 bytes")
    header = HEADER.pack(MAGIC, args.version_code, len(body),
                         zlib.crc32(body) & 0xFFFFFFFF, PRODUCT_ID, bytes(12))
    args.output.write_bytes(header + body)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
