from pathlib import Path
import hashlib
import struct
import subprocess
import sys
import tempfile
import zlib
import shutil

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.exceptions import InvalidSignature

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = struct.Struct("<6I32s64sI")
CANONICAL = struct.Struct(">6I32s")


def verify_package(package: bytes, public_key, rollback_floor: int = 0) -> bool:
    if len(package) < MANIFEST.size:
        return False
    fields = list(MANIFEST.unpack_from(package))
    magic, product, hardware, target, length, version, payload_hash, raw_sig, crc = fields
    payload = package[MANIFEST.size:]
    if magic != 0x4133464D or product != 0x41333030 or hardware != 0x00343036:
        return False
    if target != 0x08006000 or length != len(payload) or not 0 < length <= 106496:
        return False
    if version < rollback_floor or version == 0 or hashlib.sha256(payload).digest() != payload_hash:
        return False
    if zlib.crc32(package[:120]) & 0xFFFFFFFF != crc:
        return False
    digest = hashlib.sha256(CANONICAL.pack(
        magic, product, hardware, target, length, version, payload_hash)).digest()
    r = int.from_bytes(raw_sig[:32], "big")
    s = int.from_bytes(raw_sig[32:], "big")
    try:
        public_key.verify(utils.encode_dss_signature(r, s), digest,
                          ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    except (InvalidSignature, ValueError):
        return False
    return True


def test_real_signing_tool_and_tamper_contract():
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        key = ec.generate_private_key(ec.SECP256R1())
        key_path = work / "dev.pem"
        key_path.write_bytes(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption()))
        payload_path = work / "app.bin"
        payload_path.write_bytes(bytes(range(251)) * 3)
        output = work / "N32L406CBL7-DEV-KEY.pkg"
        subprocess.run([
            sys.executable, str(ROOT / "tools" / "sign_firmware.py"),
            "--key", str(key_path), "--input", str(payload_path),
            "--output", str(output), "--version-counter", "17",
        ], check=True, capture_output=True, text=True)
        package = output.read_bytes()
        assert len(package) == MANIFEST.size + payload_path.stat().st_size
        assert verify_package(package, key.public_key(), rollback_floor=17)
        assert not verify_package(package, key.public_key(), rollback_floor=18)

        # Every signed field, payload hash/signature, CRC, and payload is covered.
        for offset in (0, 4, 8, 12, 16, 20, 24, 56, 120, MANIFEST.size):
            changed = bytearray(package)
            changed[offset] ^= 1
            assert not verify_package(bytes(changed), key.public_key()), offset


def test_dev_key_create_refuse_overwrite_and_regenerate_public_header():
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        key_path = work / "dev.pem"
        header = work / "trusted_public_key.h"
        command = [
            sys.executable, str(ROOT / "tools" / "dev_key.py"),
            "--key", str(key_path), "--public-header", str(header),
        ]
        created = subprocess.run(command, check=True, capture_output=True, text=True)
        assert key_path.exists() and header.exists()
        assert "BEGIN PRIVATE KEY" not in created.stdout
        original = key_path.read_bytes()
        refused = subprocess.run(command, capture_output=True, text=True)
        assert refused.returncode != 0 and key_path.read_bytes() == original
        header.unlink()
        regenerated = subprocess.run(command + ["--regenerate-public"], check=True,
                                     capture_output=True, text=True)
        assert key_path.read_bytes() == original
        text = header.read_text(encoding="ascii")
        assert "TRUSTED_KEY_LABEL \"DEV-KEY\"" in text
        assert text.count("0x") == 64
        assert "BEGIN PRIVATE KEY" not in regenerated.stdout


def test_firmware_canonical_digest_matches_python():
    header = (ROOT / "bootloader" / "include" / "image_verify.h").read_text(encoding="utf-8")
    source = (ROOT / "bootloader" / "src" / "image_verify.c").read_text(encoding="utf-8")
    assert "void image_signature_digest(const image_manifest_t *manifest," in header
    assert "boot_ecdsa_sign" not in header and "boot_ecdsa_sign" not in source
    cc = shutil.which("gcc") or shutil.which("clang") or shutil.which("cc")
    if not cc:
        return
    expected = hashlib.sha256(CANONICAL.pack(
        0x4133464D, 0x41333030, 0x00343036, 0x08006000, 3, 17,
        hashlib.sha256(b"abc").digest())).digest()
    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        harness = work / "digest.c"
        harness.write_text(r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include "image_verify.h"
bool boot_ext_read(uint32_t a,void*b,uint32_t n){(void)a;(void)b;(void)n;return false;}
bool boot_ext_write(uint32_t a,const void*b,uint32_t n){(void)a;(void)b;(void)n;return false;}
bool boot_ext_is_complete(uint32_t a,uint32_t n){(void)a;(void)n;return false;}
bool firmware_signature_verify(const uint8_t*h,const uint8_t*s){(void)h;(void)s;return false;}
bool boot_compute_internal_hash(uint32_t a,uint32_t n,uint8_t*h){(void)a;(void)n;(void)h;return false;}
uint32_t boot_rollback_counter(void){return 0;}
int main(int argc,char**argv){
  static const uint8_t sha[32]={0xba,0x78,0x16,0xbf,0x8f,0x01,0xcf,0xea,0x41,0x41,0x40,0xde,0x5d,0xae,0x22,0x23,0xb0,0x03,0x61,0xa3,0x96,0x17,0x7a,0x9c,0xb4,0x10,0xff,0x61,0xf2,0x00,0x15,0xad};
  image_manifest_t m={0}; uint8_t out[32],expected[32]; (void)argc;
  m.magic=0x4133464d;m.product_id=0x41333030;m.hardware_id=0x00343036;
  m.target_address=0x08006000;m.image_length=3;m.version_counter=17;memcpy(m.sha256,sha,32);
  assert(strlen(argv[1])==64);for(int i=0;i<32;i++){unsigned v;assert(sscanf(argv[1]+2*i,"%2x",&v)==1);expected[i]=(uint8_t)v;}
  image_signature_digest(&m,out);assert(memcmp(out,expected,32)==0);return 0;
}
''', encoding="ascii")
        exe = work / "digest.exe"
        subprocess.run([cc, "-std=c99", "-include", "stdio.h", "-I", str(ROOT / "bootloader" / "include"),
                        "-I", str(ROOT / "include"), str(harness),
                        str(ROOT / "bootloader" / "src" / "image_verify.c"), "-o", str(exe)],
                       check=True, capture_output=True, text=True)
        subprocess.run([str(exe), expected.hex()], check=True)


if __name__ == "__main__":
    test_real_signing_tool_and_tamper_contract()
    test_dev_key_create_refuse_overwrite_and_regenerate_public_header()
    test_firmware_canonical_digest_matches_python()
    print("test_dev_signed_package: PASS")
