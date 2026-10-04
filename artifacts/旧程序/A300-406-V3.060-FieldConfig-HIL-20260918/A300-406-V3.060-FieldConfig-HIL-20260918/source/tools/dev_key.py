#!/usr/bin/env python3
"""Create a local ECDSA P-256 development key and its public C header."""

from __future__ import annotations

import argparse
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def public_header(public_key: ec.EllipticCurvePublicKey) -> str:
    numbers = public_key.public_numbers()
    raw = numbers.x.to_bytes(32, "big") + numbers.y.to_bytes(32, "big")
    rows = []
    for offset in range(0, len(raw), 8):
        rows.append("    " + ", ".join(f"0x{value:02x}" for value in raw[offset:offset + 8]))
    return """#ifndef A300_TRUSTED_PUBLIC_KEY_H
#define A300_TRUSTED_PUBLIC_KEY_H

#include <stdint.h>

#define TRUSTED_KEY_LABEL \"DEV-KEY\"
#define TRUSTED_PUBLIC_KEY_SIZE 64U

static const uint8_t trusted_public_key[TRUSTED_PUBLIC_KEY_SIZE] = {
%s
};

#endif
""" % ",\n".join(rows)


def load_p256(path: Path) -> ec.EllipticCurvePrivateKey:
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(
            key.curve, ec.SECP256R1):
        raise ValueError("existing key is not unencrypted ECDSA P-256")
    return key


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", required=True, type=Path)
    parser.add_argument("--public-header", required=True, type=Path)
    parser.add_argument("--regenerate-public", action="store_true")
    args = parser.parse_args()

    if args.key.exists():
        if not args.regenerate_public:
            parser.error("private key already exists; refusing to overwrite")
        key = load_p256(args.key)
    else:
        if args.regenerate_public:
            parser.error("cannot regenerate public header: private key is absent")
        args.key.parent.mkdir(parents=True, exist_ok=True)
        key = ec.generate_private_key(ec.SECP256R1())
        # Exclusive creation prevents a race from replacing an existing key.
        with args.key.open("xb") as stream:
            stream.write(key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption()))

    args.public_header.parent.mkdir(parents=True, exist_ok=True)
    args.public_header.write_text(public_header(key.public_key()), encoding="ascii", newline="\n")
    print(f"public header written: {args.public_header}; key-label=DEV-KEY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
