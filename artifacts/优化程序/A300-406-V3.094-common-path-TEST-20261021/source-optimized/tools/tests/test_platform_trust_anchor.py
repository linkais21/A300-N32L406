"""Catch a wrong release trust anchor using an actual platform signature.

Unlike generated-key crypto tests, this compiles the shipped trust header.
The fixture contains no device identity, token, endpoint or private key.
"""
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_platform_signature():
    fixture = json.loads((Path(__file__).parent / "fixtures" /
                          "platform_v3035_signature.json").read_text())
    cc = shutil.which("gcc") or shutil.which("clang")
    assert cc, "host C compiler required"
    digest = bytes.fromhex(fixture["sha256"])
    signature = bytes.fromhex(fixture["signature"])

    def array(data):
        return ",".join(str(b) for b in data)

    with tempfile.TemporaryDirectory(prefix="platform_trust_") as directory:
        temp = Path(directory)
        harness = temp / "test.c"
        harness.write_text(f'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include "firmware_signature.h"
#include "trusted_public_key.h"
int main(void) {{
    uint8_t digest[32]={{{array(digest)}}};
    uint8_t signature[64]={{{array(signature)}}};
    assert(TRUSTED_SIGNING_KEY_ID == {fixture['signingKeyId']}U);
    assert(firmware_signature_verify(digest, signature));
    digest[0] ^= 1;
    assert(!firmware_signature_verify(digest, signature));
    digest[0] ^= 1;
    signature[32] ^= 1;
    assert(!firmware_signature_verify(digest, signature));
    memset(signature, 0, sizeof signature);
    assert(!firmware_signature_verify(digest, signature));
    return 0;
}}
''', encoding="ascii")
        # Force the portable 32-bit arithmetic used by the Cortex-M4 build,
        # then independently exercise the host's 64-bit arithmetic.
        for word_size in (4, 8):
            exe = temp / f"verify{word_size}.exe"
            command = [cc, "-std=c99", "-O2", "-DuECC_PLATFORM=uECC_arch_other",
                       f"-DuECC_WORD_SIZE={word_size}",
                       "-DuECC_SUPPORTS_secp160r1=0", "-DuECC_SUPPORTS_secp192r1=0",
                       "-DuECC_SUPPORTS_secp224r1=0", "-DuECC_SUPPORTS_secp256k1=0",
                       "-DuECC_SUPPORTS_secp256r1=1", "-DuECC_SUPPORT_COMPRESSED_POINT=0",
                       "-I", str(ROOT / "include"),
                       "-I", str(ROOT / "third_party/micro-ecc"), str(harness),
                       str(ROOT / "src/firmware_signature.c"),
                       str(ROOT / "third_party/micro-ecc/uECC.c"), "-o", str(exe)]
            built = subprocess.run(command, capture_output=True, text=True)
            assert built.returncode == 0, built.stdout + built.stderr
            ran = subprocess.run([str(exe)], capture_output=True, text=True)
            assert ran.returncode == 0, f"shipped key rejected platform signature (word size {word_size}): {ran.stderr}"


if __name__ == "__main__":
    test_platform_signature()
    print("test_platform_trust_anchor: PASS (real platform signature, tamper rejection, 32/64-bit)")
