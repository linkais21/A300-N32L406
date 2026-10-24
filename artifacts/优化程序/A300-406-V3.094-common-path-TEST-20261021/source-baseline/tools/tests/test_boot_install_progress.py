"""Real install_resume: progress must follow verified durable pages."""
from pathlib import Path
import shutil, subprocess, tempfile

ROOT=Path(__file__).resolve().parents[2]
HARNESS=r'''
#include <assert.h>
#include <string.h>
#include <stdint.h>
#include "image_install.h"
#include "image_verify.h"
#include "bcr.h"
#include "bootloader_config.h"
static bcr_record_t current;
static image_manifest_t manifest;
static unsigned events, completed, commits, fail_commit, last_bytes;
static unsigned fail_program;
void boot_install_progress(uint32_t done,uint32_t total,bool complete) {
    assert(total==manifest.body_size && done<=total);
    assert(done==current.transaction_offset);
    assert(done>=last_bytes);last_bytes=done;++events;
    if(complete){assert(current.state==BCR_TRIAL);++completed;}
}
bcr_load_result_t bcr_load(bcr_record_t *r){*r=current;return BCR_LOAD_FOUND;}
bool bcr_commit(const bcr_record_t *r){if(++commits==fail_commit)return false;current=*r;return true;}
image_verify_result_t verify_candidate(const image_manifest_t *m){(void)m;return IMAGE_VERIFY_OK;}
bool boot_ext_read(uint32_t a,void *p,uint32_t n){if(a==0x10000 && n==sizeof manifest)memcpy(p,&manifest,n);else memset(p,0x5a,n);return true;}
bool boot_int_flash_erase(uint32_t a,uint32_t n){(void)a;(void)n;return true;}
bool boot_int_flash_program(uint32_t a,const void *p,uint32_t n){(void)a;(void)p;(void)n;return !fail_program;}
bool boot_int_flash_read(uint32_t a,void *p,uint32_t n){(void)a;memset(p,0x5a,n);return true;}
void boot_watchdog_feed(void){}
bool boot_authorization_read_at(uint32_t a,fota_authorization_t *p){(void)a;(void)p;return false;}
bool boot_authorization_load(fota_authorization_t *p){(void)p;return false;}
bool verify_external_manifest(const image_manifest_t *p,uint32_t a,uint32_t b){(void)p;(void)a;(void)b;return false;}
bool verify_external_manifest_for_promotion(const image_manifest_t *p,uint32_t a,uint32_t b){return verify_external_manifest(p,a,b);}
bool verify_legacy_package(uint32_t a,uint32_t b,legacy_image_manifest_t *p){(void)a;(void)b;(void)p;return false;}
bool boot_ext_write(uint32_t a,const void *p,uint32_t n){(void)a;(void)p;(void)n;return false;}
bool boot_ext_erase(uint32_t a,uint32_t n){(void)a;(void)n;return false;}
uint32_t image_crc32(const void *p,uint32_t n){(void)p;(void)n;return 0;}
bool boot_app_vectors_valid(uint32_t a){(void)a;return false;}
void boot_jump_to(uint32_t a){(void)a;}
static void reset(uint32_t offset){
 memset(&manifest,0,sizeof manifest);manifest.body_size=105208;manifest.version=3046;
 memset(&current,0,sizeof current);current.state=BCR_PENDING;current.transaction_offset=offset;
 current.transaction_length=manifest.body_size;current.image_version=manifest.version;current.target_address=APP_FLASH_BASE;
 events=completed=commits=fail_commit=last_bytes=fail_program=0;
}
int main(void){
 reset(0);assert(install_resume(0));assert(completed==1 && events>=10 && events<=12);
 reset(4096);assert(install_resume(4096));assert(completed==1);
 reset(0);fail_program=1;assert(!install_resume(0));assert(completed==0 && last_bytes==0);
 reset(0);fail_commit=1;assert(!install_resume(0));assert(completed==0 && last_bytes==0);
 reset(0);fail_commit=53;assert(!install_resume(0));assert(completed==0);
 reset(105208);fail_commit=1;assert(!install_resume(105208));assert(events==0);
 return 0;
}
'''
def main():
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp);(p/'h.c').write_text(HARNESS,encoding='ascii')
        cmd=[shutil.which('gcc') or shutil.which('clang'),'-std=c99','-O1','-ffunction-sections','-fdata-sections',
             '-I',str(ROOT/'bootloader/include'),'-I',str(ROOT/'include'),str(p/'h.c'),
             str(ROOT/'bootloader/src/image_install.c'),'-Wl,--gc-sections','-o',str(p/'h.exe')]
        subprocess.run(cmd,check=True);subprocess.run([str(p/'h.exe')],check=True)
    print('boot install progress PASS')
if __name__=='__main__':main()
