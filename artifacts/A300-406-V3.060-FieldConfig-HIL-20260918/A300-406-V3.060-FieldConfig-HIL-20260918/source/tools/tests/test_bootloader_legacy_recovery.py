"""Compile the production verifier and exercise legacy recovery compatibility."""
from pathlib import Path
import hashlib
import shutil
import struct
import subprocess
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[2]


def test_legacy_signed_package_is_recovery_only_and_fail_closed():
    cc = shutil.which("gcc") or shutil.which("clang")
    assert cc, "host C compiler required"
    body = struct.pack("<II", 0x20001000, 0x08006009) + b"legacy-body" * 23
    digest = hashlib.sha256(body).digest()
    fields = (0x4133464D, 0x41333030, 0x343036, 0x08006000, len(body), 3001)
    canonical_digest = hashlib.sha256(struct.pack(">6I", *fields) + digest).digest()
    prefix = struct.pack("<6I", *fields) + digest + bytes([0x5A]) * 64
    package = prefix + struct.pack("<I", zlib.crc32(prefix) & 0xFFFFFFFF) + body
    source = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "image_verify.h"
#define BASE 0x0C0000UL
static uint8_t flash[2*1024*1024];
static uint32_t floor_value;static bool signature_ok=true;
static const uint8_t expected_digest[]={__DIGEST__};
static const uint8_t package[]={__PACKAGE__};
bool boot_ext_read(uint32_t a,void *p,uint32_t n){if(a+n>sizeof flash)return false;memcpy(p,flash+a,n);return true;}
bool boot_ext_write(uint32_t a,const void*p,uint32_t n){(void)a;(void)p;(void)n;return false;}
bool boot_ext_erase(uint32_t a,uint32_t n){(void)a;(void)n;return false;}
bool boot_ext_is_complete(uint32_t a,uint32_t n){return a+n<=sizeof flash;}
bool boot_rollback_counter(uint32_t *out){*out=floor_value;return true;}
bool boot_app_vectors_valid(uint32_t a){(void)a;return true;}
bool boot_compute_internal_hash(uint32_t a,uint32_t n,uint8_t h[32]){(void)a;(void)n;(void)h;return false;}
void boot_watchdog_feed(void){}
bool firmware_signature_verify(const uint8_t *d,const uint8_t *s){return signature_ok&&!memcmp(d,expected_digest,32)&&s[0]==0x5a;}
static void load(void){memset(flash,0xff,sizeof flash);memcpy(flash+BASE,package,sizeof package);floor_value=0;signature_ok=true;}
int main(void){
 legacy_image_manifest_t m;
 load();assert(verify_legacy_package(BASE,0x100000,&m));assert(m.version_counter==3001);
 assert(verify_candidate((const image_manifest_t *)(flash+BASE))!=IMAGE_VERIFY_OK);
 load();flash[BASE+120]^=1;assert(!verify_legacy_package(BASE,0x100000,0));
 load();flash[BASE+124+9]^=1;assert(!verify_legacy_package(BASE,0x100000,0));
 load();signature_ok=false;assert(!verify_legacy_package(BASE,0x100000,0));
 load();floor_value=3002;assert(!verify_legacy_package(BASE,0x100000,0));
 load();flash[BASE+12]^=1;assert(!verify_legacy_package(BASE,0x100000,0));
 puts("legacy recovery verifier: valid + CRC/hash/signature/target/rollback rejects PASS");return 0;
}
'''.replace("__DIGEST__", ",".join(map(str, canonical_digest))).replace(
        "__PACKAGE__", ",".join(map(str, package)))
    with tempfile.TemporaryDirectory(prefix="legacy_recovery_") as directory:
        temp = Path(directory)
        harness = temp / "legacy.c"
        exe = temp / "legacy.exe"
        harness.write_text(source, encoding="ascii")
        result = subprocess.run([cc, "-std=c99", "-O1", "-Wall", "-Wextra", "-Werror",
                                 "-I", str(ROOT / "bootloader/include"), "-I", str(ROOT / "include"),
                                 str(harness), str(ROOT / "bootloader/src/image_verify.c"), "-o", str(exe)],
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        result = subprocess.run([str(exe)], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        print(result.stdout.strip())


if __name__ == "__main__":
    test_legacy_signed_package_is_recovery_only_and_fail_closed()
    print("test_bootloader_legacy_recovery: PASS")
