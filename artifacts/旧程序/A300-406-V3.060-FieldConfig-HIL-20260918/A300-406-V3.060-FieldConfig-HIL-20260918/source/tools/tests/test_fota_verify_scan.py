"""Compile the production manifest verifier; measure candidate reads, not timing.

Flash/BCR/signature boundaries are injected. SHA and CRC use production C.
The real ECC trust anchor is covered by test_platform_trust_anchor.py.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def test_verify_scan():
    source = (ROOT / "src/fota.c").read_text(encoding="utf-8")
    verifier = source[source.index("static void fota_diag_hex("):
                      source.index("bool fota_bcr_commit_pending(")]
    harness = r'''
#include <assert.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include "fota.h"
#include "boot_contract.h"
#include "sha256.h"
#include "crc32.h"
#include "trusted_public_key.h"
#define APP_FLASH_BASE 0x08006000UL
#define APP_FLASH_SIZE 106496U
#define EXT_FLASH_OWNER_OTA 1
typedef enum { FOTA_BCR_IO_ERROR, FOTA_BCR_FOUND, FOTA_BCR_ABSENT } fota_bcr_result_t;
static uint8_t package[APP_FLASH_SIZE+32], s_package_sha256[32], s_signature[64];
static uint32_t s_expected, s_signing_key_id=TRUSTED_SIGNING_KEY_ID;
static uint32_t bytes_read, reads, fail_read, floor_version, feeds, signature_calls;
static bool locked=true, signature_ok=true, bcr_error;
static char log_text[2048];
static void dbg_printf(const char *fmt, ...) {
    va_list ap; va_start(ap,fmt);
    vsnprintf(log_text+strlen(log_text),sizeof log_text-strlen(log_text),fmt,ap);
    va_end(ap);
}
static void IWDG_ReloadKey(void) { feeds++; }
static uint32_t fota_product_id(void) { return FOTA_PACKAGE_PRODUCT_ID; }
static fota_bcr_result_t fota_bcr_load(bcr_record_t *r) {
    r->rollback_floor=floor_version;
    return bcr_error ? FOTA_BCR_IO_ERROR : FOTA_BCR_FOUND;
}
static bool ext_flash_read(int owner,uint32_t addr,void *buf,uint32_t n) {
    assert(owner==EXT_FLASH_OWNER_OTA);
    reads++;
    if (!locked || reads==fail_read) return false;
    assert(addr>=FOTA_FLASH_ADDR && addr-FOTA_FLASH_ADDR+n<=s_expected);
    assert(n<=256);
    memcpy(buf,package+addr-FOTA_FLASH_ADDR,n); bytes_read+=n; return true;
}
static bool firmware_signature_verify(const uint8_t *digest,const uint8_t *sig) {
    assert(sig==s_signature && memcmp(digest,s_package_sha256,32)==0);
    signature_calls++; return signature_ok;
}
'''
    cases = r'''
static fota_package_header_t header;
static void hash_package(void) {
    sha256_ctx_t sha;
    memcpy(package,&header,sizeof header);
    sha256_init(&sha); sha256_update(&sha,package,s_expected);
    sha256_final(&sha,s_package_sha256);
}
static void setup(uint32_t size) {
    uint32_t vectors[2]={0x20001000U,APP_FLASH_BASE+1U};
    header=(fota_package_header_t){FOTA_PACKAGE_HEADER_MAGIC,3047,size,0,FOTA_PACKAGE_PRODUCT_ID,{0}};
    s_expected=sizeof header+size;
    for(uint32_t i=0;i<size;i++) package[sizeof header+i]=(uint8_t)(i*17U+3U);
    memcpy(package+sizeof header,vectors,sizeof vectors);
    header.body_crc32=crc32_compute(package+sizeof header,size);
    hash_package();
    bytes_read=reads=fail_read=feeds=signature_calls=floor_version=0;
    log_text[0]=0; locked=signature_ok=true; bcr_error=false;
}
static void rejected(const char *stage) {
    assert(!fota_verify_manifest(&header,sizeof header));
    assert(strstr(log_text,stage));
}
int main(void) {
    const uint32_t sizes[]={8,223,224,225,255,256,257,511,512,513,APP_FLASH_SIZE};
    for(unsigned i=0;i<sizeof sizes/sizeof sizes[0];i++) {
        setup(sizes[i]);
        assert(fota_verify_manifest(&header,sizeof header));
        /* One package scan and the existing independent vector read. */
        assert(bytes_read==s_expected+8U);
        assert(feeds==(s_expected+255U)/256U);
        assert(signature_calls==1);
        bytes_read=0;
        assert(fota_verify_manifest(&header,sizeof header));
        assert(bytes_read==s_expected+8U);
    }
    setup(513); s_package_sha256[0]^=1; rejected("stage=sha256");
    assert(strstr(log_text,"body_crc=") && signature_calls==0);
    {
        char expected_crc[32];
        snprintf(expected_crc,sizeof expected_crc,"body_crc=%08lx",(unsigned long)header.body_crc32);
        assert(strstr(log_text,expected_crc));
    }
    setup(513);
    {
        sha256_ctx_t body_sha;
        sha256_init(&body_sha); sha256_update(&body_sha,package+32,header.body_size);
        sha256_final(&body_sha,s_package_sha256);
        rejected("stage=sha256"); assert(strstr(log_text,"body_match=1"));
    }
    setup(513); header.body_crc32^=1; hash_package(); rejected("stage=crc");
    assert(signature_calls==1);
    setup(513); signature_ok=false; rejected("stage=signature");
    setup(513); signature_ok=false; header.body_crc32^=1; hash_package();
    rejected("stage=signature"); assert(!strstr(log_text,"stage=crc"));
    setup(513); package[40]^=1; rejected("stage=sha256");
    for(uint32_t i=1;i<=4;i++) {
        setup(513); fail_read=i;
        rejected(i==4 ? "stage=vectors-read" : "stage=package-read");
    }
    setup(513); locked=false; rejected("stage=package-read");
    setup(513); bcr_error=true; rejected("stage=bcr-read"); assert(reads==0);
    setup(513); floor_version=3048; assert(!fota_verify_manifest(&header,sizeof header)); assert(reads==0);
    setup(513); header.reserved[0]=1; rejected("stage=header"); assert(reads==0);
    setup(513); memset(package+32,0,8);
    header.body_crc32=crc32_compute(package+32,header.body_size); hash_package();
    rejected("stage=vectors");
    puts("manifest scan: boundaries, read budget, rejection order, failures, repeat PASS");
    return 0;
}
'''
    cc = shutil.which("gcc") or shutil.which("clang")
    assert cc, "host C compiler required"
    with tempfile.TemporaryDirectory(prefix="fota_scan_") as directory:
        temp = Path(directory)
        c = temp / "scan.c"
        c.write_text(harness + verifier + cases, encoding="utf-8")
        exe = temp / "scan.exe"
        subprocess.run([cc, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                        "-I", str(ROOT / "include"), str(c),
                        str(ROOT / "src/sha256.c"), str(ROOT / "src/crc32.c"),
                        "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    test_verify_scan()
