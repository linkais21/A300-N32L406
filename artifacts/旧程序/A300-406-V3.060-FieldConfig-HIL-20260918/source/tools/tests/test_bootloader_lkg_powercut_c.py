"""Production-C dual-slot LKG promotion under every persistent operation cut."""
from pathlib import Path
import hashlib
import shutil
import struct
import subprocess
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[2]


def _package(version, fill, generation):
    body = struct.pack("<II", 0x20001000, 0x08006009) + bytes([fill]) * 504
    header = struct.pack("<IIIII12s", 0xA300B007, version, len(body),
                         zlib.crc32(body) & 0xFFFFFFFF, 0x41333030, bytes(12))
    package = header + body
    auth_body = struct.pack("<9I", 0x41555448, 1, 140, generation, len(package),
                            version, 0x08006000, zlib.crc32(body) & 0xFFFFFFFF, 1)
    auth_body += hashlib.sha256(package).digest() + bytes([0x5A]) * 64
    auth = auth_body + struct.pack("<II", zlib.crc32(auth_body) & 0xFFFFFFFF, 0x41555443)
    return package, auth


def test_production_c_lkg_promotion_survives_every_operation_cut():
    cc = shutil.which("gcc") or shutil.which("clang")
    assert cc, "host C compiler required"
    old_pkg, old_auth = _package(3001, 0x31, 7)
    new_pkg, new_auth = _package(3002, 0x42, 2)
    source = r'''
#include <assert.h>
#include <setjmp.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "bcr.h"
#include "bootloader_config.h"
#include "image_install.h"
#include "image_verify.h"
static uint8_t flash[2*1024*1024],baseline[2*1024*1024];
static const uint8_t old_pkg[]={__OLD_PKG__},old_auth[]={__OLD_AUTH__};
static const uint8_t new_pkg[]={__NEW_PKG__},new_auth[]={__NEW_AUTH__};
static int cut=-1,steps;static unsigned jumps;static uint32_t floor_value=3001;static jmp_buf reset;
static void step(void){int current=steps++;if(cut>=0&&current==cut)longjmp(reset,1);}
bool boot_ext_read(uint32_t a,void*p,uint32_t n){assert(a+n<=sizeof flash);step();memcpy(p,flash+a,n);step();return true;}
bool boot_ext_write(uint32_t a,const void*p,uint32_t n){const uint8_t*q=p;assert(a+n<=sizeof flash);step();for(uint32_t i=0;i<n;i++){assert((flash[a+i]&q[i])==q[i]);flash[a+i]&=q[i];}step();return true;}
bool boot_ext_erase(uint32_t a,uint32_t n){assert(a%4096==0&&n%4096==0&&a+n<=sizeof flash);step();memset(flash+a,0xff,n);step();return true;}
bool boot_ext_is_complete(uint32_t a,uint32_t n){return a+n<=sizeof flash;}
bool boot_rollback_counter(uint32_t*out){*out=floor_value;return true;}
bool boot_app_vectors_valid(uint32_t a){(void)a;return true;}
bool boot_compute_internal_hash(uint32_t a,uint32_t n,uint8_t h[32]){(void)a;(void)n;(void)h;return false;}
bool firmware_signature_verify(const uint8_t*d,const uint8_t*s){(void)d;return s[0]==0x5a;}
void boot_install_progress(uint32_t done, uint32_t total, bool complete) {(void)done;(void)total;(void)complete;}
void boot_watchdog_feed(void){}
bcr_load_result_t bcr_load(bcr_record_t*out){memset(out,0,sizeof *out);out->state=BCR_ACTIVE;out->image_version=3002;out->transaction_length=sizeof(new_pkg)-32;out->target_address=APP_FLASH_BASE;out->rollback_floor=floor_value;return BCR_LOAD_FOUND;}
bool bcr_commit(const bcr_record_t*r){step();floor_value=r->rollback_floor;step();return true;}
bool boot_int_flash_erase(uint32_t a,uint32_t n){(void)a;(void)n;return false;}
bool boot_int_flash_program(uint32_t a,const void*p,uint32_t n){(void)a;(void)p;(void)n;return false;}
bool boot_int_flash_read(uint32_t a,void*p,uint32_t n){(void)a;(void)p;(void)n;return false;}
void boot_jump_to(uint32_t a){assert(a==APP_FLASH_BASE);jumps++;}
static void seed(void){memset(flash,0xff,sizeof flash);memcpy(flash+LKG_SLOT_B_BASE,old_pkg,sizeof old_pkg);memcpy(flash+LKG_SLOT_B_AUTH_ADDR,old_auth,sizeof old_auth);memcpy(flash+0x010000,new_pkg,sizeof new_pkg);memcpy(flash+FOTA_AUTH_SLOT_A_ADDR,new_auth,sizeof new_auth);memcpy(baseline,flash,sizeof flash);}
static bool any_physical_lkg(void){image_manifest_t h;uint32_t saved=floor_value;bool valid;floor_value=0;valid=(boot_ext_read(LKG_SLOT_A_BASE,&h,sizeof h)&&verify_external_manifest(&h,LKG_SLOT_A_BASE,LKG_SLOT_A_AUTH_ADDR))||(boot_ext_read(LKG_SLOT_B_BASE,&h,sizeof h)&&verify_external_manifest(&h,LKG_SLOT_B_BASE,LKG_SLOT_B_AUTH_ADDR));floor_value=saved;return valid;}
static bool new_lkg_valid(void){image_manifest_t h;return (boot_ext_read(LKG_SLOT_A_BASE,&h,sizeof h)&&h.version==3002&&verify_external_manifest(&h,LKG_SLOT_A_BASE,LKG_SLOT_A_AUTH_ADDR))||(boot_ext_read(LKG_SLOT_B_BASE,&h,sizeof h)&&h.version==3002&&verify_external_manifest(&h,LKG_SLOT_B_BASE,LKG_SLOT_B_AUTH_ADDR));}
int main(void){
 int total;
 seed();cut=-1;steps=0;jumps=0;assert(bootloader_select_image()==false&&jumps==1);total=steps;assert(total>0);
 for(int point=0;point<total;point++){
  memcpy(flash,baseline,sizeof flash);steps=0;cut=point;jumps=0;
  if(setjmp(reset)==0)(void)bootloader_select_image();
  cut=-1;assert(any_physical_lkg());
  jumps=0;(void)bootloader_select_image();assert(jumps==1);
  assert(floor_value==3002&&new_lkg_valid());
 }
 printf("production C LKG promotion: %d operation cuts PASS\n",total);return 0;
}
'''
    for name, value in (("__OLD_PKG__", old_pkg), ("__OLD_AUTH__", old_auth),
                        ("__NEW_PKG__", new_pkg), ("__NEW_AUTH__", new_auth)):
        source = source.replace(name, ",".join(map(str, value)))
    with tempfile.TemporaryDirectory(prefix="lkg_powercut_c_") as directory:
        temp = Path(directory); harness = temp / "lkg.c"; exe = temp / "lkg.exe"
        harness.write_text(source, encoding="ascii")
        result = subprocess.run([cc, "-std=c99", "-O1", "-Wall", "-Wextra", "-Werror",
                                 "-I", str(ROOT / "bootloader/include"), "-I", str(ROOT / "include"),
                                 str(harness), str(ROOT / "bootloader/src/image_verify.c"),
                                 str(ROOT / "bootloader/src/image_install.c"), "-o", str(exe)],
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        result = subprocess.run([str(exe)], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        print(result.stdout.strip())


if __name__ == "__main__":
    test_production_c_lkg_promotion_survives_every_operation_cut()
    print("test_bootloader_lkg_powercut_c: PASS")
