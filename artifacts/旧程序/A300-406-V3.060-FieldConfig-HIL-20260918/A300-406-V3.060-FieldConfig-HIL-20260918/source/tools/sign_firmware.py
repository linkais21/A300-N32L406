#!/usr/bin/env python3
"""Create an N32L406CBL7 development-key signed App package."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import struct
import zlib

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

MANIFEST_MAGIC = 0x4133464D
PRODUCT_ID = 0x41333030
HARDWARE_ID = 0x00343036
TARGET_ADDRESS = 0x08006000
APP_MAX_SIZE = 106496
MANIFEST = struct.Struct("<6I32s64sI")
CANONICAL = struct.Struct(">6I32s")
OUTPUT_LABEL = "N32L406CBL7-DEV-KEY"


def positive_u32(value: str) -> int:
    parsed = int(value, 0)
    if not 0 < parsed <= 0xFFFFFFFF:
        raise argparse.ArgumentTypeError("version counter must be 1..0xffffffff")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", required=True, type=Path)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--version-counter", required=True, type=positive_u32)
    parser.add_argument("--product-id", type=lambda x: int(x, 0), default=PRODUCT_ID)
    parser.add_argument("--hardware-id", type=lambda x: int(x, 0), default=HARDWARE_ID)
    parser.add_argument("--target-address", type=lambda x: int(x, 0), default=TARGET_ADDRESS)
    args = parser.parse_args()

    if args.product_id != PRODUCT_ID or args.hardware_id != HARDWARE_ID:
        parser.error("product/hardware ID does not match A300_406")
    if args.target_address != TARGET_ADDRESS:
        parser.error("target address must be 0x08006000")
    if OUTPUT_LABEL not in args.output.name:
        parser.error(f"output filename must contain {OUTPUT_LABEL}")

    payload = args.input.read_bytes()
    if not 0 < len(payload) <= APP_MAX_SIZE:
        parser.error(f"input length must be 1..{APP_MAX_SIZE} bytes")
    private_key = serialization.load_pem_private_key(args.key.read_bytes(), password=None)
    if not isinstance(private_key, ec.EllipticCurvePrivateKey) or not isinstance(
            private_key.curve, ec.SECP256R1):
        parser.error("key must be an unencrypted ECDSA P-256 private key")

    payload_hash = hashlib.sha256(payload).digest()
    canonical = CANONICAL.pack(
        MANIFEST_MAGIC, args.product_id, args.hardware_id, args.target_address,
        len(payload), args.version_counter, payload_hash)
    digest = hashlib.sha256(canonical).digest()
    der = private_key.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    r, s = utils.decode_dss_signature(der)
    raw_signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    without_crc = MANIFEST.pack(
        MANIFEST_MAGIC, args.product_id, args.hardware_id, args.target_address,
        len(payload), args.version_counter, payload_hash, raw_signature, 0)
    crc = zlib.crc32(without_crc[:120]) & 0xFFFFFFFF
    package = MANIFEST.pack(
        MANIFEST_MAGIC, args.product_id, args.hardware_id, args.target_address,
        len(payload), args.version_counter, payload_hash, raw_signature, crc) + payload
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(package)
    print(f"signed {args.output.name}: {len(payload)} bytes, key-label=DEV-KEY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
