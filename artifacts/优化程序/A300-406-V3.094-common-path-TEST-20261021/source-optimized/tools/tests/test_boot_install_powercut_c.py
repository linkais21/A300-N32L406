"""Production installer + BCR under torn NOR/internal writes and reboot."""
import hashlib
import shutil
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = r'''
#include <assert.h>
#include <setjmp.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include "bcr.h"
#include "image_verify.h"
#include "image_install.h"
#include "bootloader_config.h"
static unsigned char ext[2*1024*1024],internal[APP_FLASH_MAX_SIZE],baseline[8192];
static const unsigned char package[]={PACKAGE},auth[]={AUTH};
static int cut=-1,steps;static jmp_buf reset;
static void step(void){if(cut>=0 && steps++==cut)longjmp(reset,1);}
static bool read_bytes(const unsigned char *src,void *p,uint32_t n){
    step();memcpy(p,src,n);step();return true;
}
static bool erase_bytes(unsigned char *p,uint32_t n){
    step();memset(p,255,n/2);step();memset(p+n/2,255,n-n/2);step();return true;
}
static bool program_bytes(unsigned char *p,const void *v,uint32_t n){
    const unsigned char *q=v;step();
    for(uint32_t i=0;i<n;i++){assert((p[i]&q[i])==q[i]);p[i]&=q[i];if(i==n/2)step();}
    step();return true;
}
bool boot_ext_read(uint32_t a,void *p,uint32_t n){assert(a+n<=sizeof ext);return read_bytes(ext+a,p,n);}
bool boot_ext_write(uint32_t a,const void *p,uint32_t n){assert(a+n<=sizeof ext);return program_bytes(ext+a,p,n);}
bool boot_ext_erase(uint32_t a,uint32_t n){assert(a%4096==0 && n%4096==0 && a+n<=sizeof ext);return erase_bytes(ext+a,n);}
bool boot_ext_is_complete(uint32_t a,uint32_t n){return a+n<=sizeof ext;}
bool boot_bcr_read(uint32_t a,void*p,uint32_t n){return boot_ext_read(a,p,n);}
bool boot_bcr_write(uint32_t a,const void*p,uint32_t n){return boot_ext_write(a,p,n);}
bool boot_bcr_erase(uint32_t a){return boot_ext_erase(a,4096);}
bool boot_bcr_readback(uint32_t a,const void*p,uint32_t n){step();bool ok=!memcmp(ext+a,p,n);step();return ok;}
void boot_bcr_retry_wait(unsigned attempt,bool io){(void)attempt;(void)io;}
bool boot_int_flash_read(uint32_t a,void*p,uint32_t n){assert(a>=APP_FLASH_BASE && a-APP_FLASH_BASE+n<=sizeof internal);return read_bytes(internal+a-APP_FLASH_BASE,p,n);}
bool boot_int_flash_program(uint32_t a,const void*p,uint32_t n){assert(a>=APP_FLASH_BASE && a-APP_FLASH_BASE+n<=sizeof internal);return program_bytes(internal+a-APP_FLASH_BASE,p,n);}
bool boot_int_flash_erase(uint32_t a,uint32_t n){
    bcr_record_t committed;
    assert(bcr_load(&committed)==BCR_LOAD_FOUND && committed.reserved==0U);
    assert(a%2048==0 && n%2048==0 && a>=APP_FLASH_BASE && a-APP_FLASH_BASE+n<=sizeof internal);
    return erase_bytes(internal+a-APP_FLASH_BASE,n);
}
bool boot_rollback_counter(uint32_t *v){*v=1;return true;}
bool firmware_signature_verify(const uint8_t *d,const uint8_t *s){(void)d;return s[0]==0x5a;}
void boot_watchdog_feed(void){}
void boot_install_progress(uint32_t d,uint32_t n,bool c){(void)d;(void)n;(void)c;}
bool boot_app_vectors_valid(uint32_t a){(void)a;return true;}
void boot_jump_to(uint32_t a){(void)a;assert(0);}
static void install(void){bcr_record_t r;assert(bcr_load(&r)==BCR_LOAD_FOUND);if(r.state==BCR_PENDING)assert(install_resume(r.transaction_offset));}
int main(void){
    bcr_record_t r={0};int count;static int scenarios;
    memset(ext,255,sizeof ext);memcpy(ext+0x10000,package,sizeof package);memcpy(ext+FOTA_AUTH_SLOT_A_ADDR,auth,sizeof auth);
    r.sequence=1;r.state=BCR_PENDING;r.reserved=BCR_INSTALL_NOT_STARTED;
    r.image_version=3002;r.transaction_length=sizeof package-32;r.target_address=APP_FLASH_BASE;
    assert(bcr_commit(&r));assert(BCR_SLOT_B_ADDR==BCR_SLOT_A_ADDR+4096);
    memcpy(baseline,ext+BCR_SLOT_A_ADDR,8192);memset(internal,0x31,sizeof internal);
    cut=100000000;steps=0;install();count=steps;cut=-1;
    for(int point=0;point<=count;point++){
        /* Small/final-partial-page images are exhaustive; the capacity limit
         * samples the long path and exhausts the final commit/readback tail. */
        if(sizeof package>8192U && point%31 && point<count-64)continue;
        ++scenarios;
        memcpy(ext+BCR_SLOT_A_ADDR,baseline,8192);memset(internal,0x31,sizeof internal);steps=0;cut=point;
        if(setjmp(reset)==0)install();
        cut=-1;install();assert(bcr_load(&r)==BCR_LOAD_FOUND && r.state==BCR_TRIAL);
        assert(r.transaction_offset==sizeof package-32);
        assert(!memcmp(internal,package+32,sizeof package-32));
    }
    printf("install C: %u bytes, %d cuts including torn erase/program/BCR/full readback PASS\n",(unsigned)(sizeof package-32),scenarios);return 0;
}
'''


def main():
    with tempfile.TemporaryDirectory(prefix="boot_install_cuts_") as td:
        p = Path(td)
        for size in (2048, 2049, 4097, 106496):
            body = struct.pack("<II", 0x20006000, 0x08006009) + bytes([0x5a]) * (size-8)
            crc = zlib.crc32(body)
            package = struct.pack("<IIIII12s", 0xA300B007, 3002, size, crc, 0x41333030, bytes(12)) + body
            auth = struct.pack("<9I", 0x41555448, 1, 140, 1, len(package), 3002, 0x08006000, crc, 1)
            auth += hashlib.sha256(package).digest() + bytes([0x5a]) * 64
            auth += struct.pack("<II", zlib.crc32(auth), 0x41555443)
            source = SOURCE.replace("{PACKAGE}", "{" + ",".join(map(str, package)) + "}")
            source = source.replace("{AUTH}", "{" + ",".join(map(str, auth)) + "}")
            (p / "h.c").write_text(source, encoding="ascii")
            exe = p / "test.exe"
            subprocess.run([shutil.which("gcc") or shutil.which("clang"), "-std=c99", "-O1",
                            "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "bootloader/include"),
                            "-I", str(ROOT / "include"), str(p / "h.c"),
                            *[str(ROOT / "bootloader/src" / name) for name in ("bcr.c", "image_verify.c", "image_install.c")],
                            "-o", str(exe)], check=True, timeout=60)
            subprocess.run([str(exe)], check=True, timeout=60)


if __name__ == "__main__":
    main()
