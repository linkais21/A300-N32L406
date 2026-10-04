from pathlib import Path
import hashlib
import shutil
import subprocess
import tempfile

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, utils

ROOT = Path(__file__).resolve().parents[2]


def test_real_firmware_verifier():
    cc = shutil.which("gcc") or shutil.which("clang") or shutil.which("cc")
    if not cc:
        raise AssertionError("host C compiler required for crypto verifier test")
    private = ec.generate_private_key(ec.SECP256R1())
    digest = hashlib.sha256(b"A300 firmware signature vector").digest()
    der = private.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    r, s = utils.decode_dss_signature(der)
    signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    public = private.public_key().public_numbers()
    public_bytes = public.x.to_bytes(32, "big") + public.y.to_bytes(32, "big")
    order = int("FFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551", 16)
    wrong_private = ec.generate_private_key(ec.SECP256R1())
    wrong_public = wrong_private.public_key().public_numbers()
    wrong_public_bytes = (wrong_public.x.to_bytes(32, "big") +
                          wrong_public.y.to_bytes(32, "big"))

    def c_array(data):
        return ",".join(f"0x{x:02x}" for x in data)

    def build_and_run(work, name, embedded_public, expect_valid):
        work = Path(td)
        include_dir = work / name
        include_dir.mkdir()
        (include_dir / "trusted_public_key.h").write_text(
            "#include <stdint.h>\n#define TRUSTED_PUBLIC_KEY_SIZE 64U\n"
            f"static const uint8_t trusted_public_key[64]={{{c_array(embedded_public)}}};\n",
            encoding="ascii")
        (include_dir / "harness.c").write_text(f'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include "firmware_signature.h"
static const uint8_t digest[32]={{{c_array(digest)}}};
static const uint8_t signature[64]={{{c_array(signature)}}};
int main(void){{
 uint8_t d[32],s[64];memcpy(d,digest,32);memcpy(s,signature,64);
 assert(firmware_signature_verify(d,s)=={1 if expect_valid else 0});
 if (!{1 if expect_valid else 0}) return 0;
 d[0]^=1;assert(!firmware_signature_verify(d,s));d[0]^=1;
 s[0]^=1;assert(!firmware_signature_verify(d,s));memcpy(s,signature,64);
 s[32]^=1;assert(!firmware_signature_verify(d,s));memcpy(s,signature,64);
 memset(s,0,32);assert(!firmware_signature_verify(d,s));memcpy(s,signature,64);
 memset(s+32,0,32);assert(!firmware_signature_verify(d,s));memcpy(s,signature,64);
 const uint8_t order_bytes[32]={{{c_array(order.to_bytes(32, "big"))}}};
 memcpy(s,order_bytes,32);assert(!firmware_signature_verify(d,s));memcpy(s,signature,64);
 memcpy(s+32,order_bytes,32);assert(!firmware_signature_verify(d,s));
 return 0;
}}
''', encoding="ascii")
        exe = include_dir / "verify.exe"
        flags = ["-std=c99", "-DuECC_SUPPORTS_secp160r1=0", "-DuECC_SUPPORTS_secp192r1=0",
                 "-DuECC_SUPPORTS_secp224r1=0", "-DuECC_SUPPORTS_secp256k1=0",
                 "-DuECC_SUPPORTS_secp256r1=1", "-DuECC_SUPPORT_COMPRESSED_POINT=0"]
        subprocess.run([cc, *flags, "-I", str(include_dir), "-I", str(ROOT / "include"),
                        "-I", str(ROOT / "third_party" / "micro-ecc"),
                        str(include_dir / "harness.c"), str(ROOT / "src" / "firmware_signature.c"),
                        str(ROOT / "third_party" / "micro-ecc" / "uECC.c"), "-o", str(exe)],
                       check=True, capture_output=True, text=True)
        subprocess.run([str(exe)], check=True)

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        build_and_run(work, "valid-key", public_bytes, True)
        flipped_public = bytearray(public_bytes)
        flipped_public[0] ^= 1
        build_and_run(work, "flipped-public-key", bytes(flipped_public), False)
        build_and_run(work, "wrong-public-key", wrong_public_bytes, False)


if __name__ == "__main__":
    test_real_firmware_verifier()
    print("test_firmware_signature: PASS")
