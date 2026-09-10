"""Production C journal under byte-granular power loss; no Python journal mirror."""
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).parents[2]

NOR = r'''
#include <assert.h>
#include <setjmp.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include "fota_checkpoint.h"
#include "ext_flash_store.h"
#include "crc32.h"
static unsigned char flash[2*1024*1024];
static int locked=EXT_FLASH_OWNER_OTA, cut=-1, steps;
static jmp_buf reset;
static unsigned erase_count, erased[256], full_reads, body_writes, marker_writes;
static unsigned candidate_erase_count, candidate_erased[256];
static int fail_read, corrupt_read, corrupt_final;
static void step(void){if(cut>=0 && steps++==cut)longjmp(reset,1);}
bool ext_flash_read(ext_flash_owner_t owner,uint32_t addr,void *out,uint32_t n){
    if((int)owner!=locked || fail_read)return false;
    assert(addr+n<=sizeof flash);
    if(n==sizeof(fota_checkpoint_t))++full_reads;
    for(uint32_t i=0;i<n;i++){step();((uint8_t*)out)[i]=flash[addr+i];}
    if((corrupt_read || (corrupt_final && marker_writes)) && n==sizeof(fota_checkpoint_t))((uint8_t*)out)[20]^=1;
    step();return true;
}
bool ext_flash_erase(ext_flash_owner_t owner,uint32_t addr,uint32_t n){
    if((int)owner!=locked)return false;
    assert(n==4096 && addr%4096==0 && addr+n<=sizeof flash);
    assert(erase_count<256);erased[erase_count++]=addr;
    if(addr>=0x10000 && addr<0x80000){assert(candidate_erase_count<256);candidate_erased[candidate_erase_count++]=addr;}
    for(uint32_t i=0;i<n;i++){step();flash[addr+i]=255;}step();return true;
}
bool ext_flash_write_verified(ext_flash_owner_t owner,uint32_t addr,const void *in,uint32_t n){
    const uint8_t *p=in;if((int)owner!=locked)return false;
    assert(addr+n<=sizeof flash);
    if(addr==0x102000 || addr==0x103000){
        ++body_writes;assert(n==sizeof(fota_checkpoint_t)-4);
        for(unsigned j=0;j<4;j++)assert(flash[addr+n+j]==255);
    }
    if(addr==0x102000+sizeof(fota_checkpoint_t)-4 || addr==0x103000+sizeof(fota_checkpoint_t)-4){
        ++marker_writes;assert(n==4);
    }
    for(uint32_t i=0;i<n;i++){step();assert((flash[addr+i]&p[i])==p[i]);flash[addr+i]&=p[i];}
    for(uint32_t i=0;i<n;i++){step();assert(flash[addr+i]==p[i]);}step();return true;
}
'''


def run_host(source, name, fota=False):
    cc = shutil.which("gcc") or shutil.which("clang")
    assert cc, "host C compiler required; checkpoint tests must not silently skip"
    with tempfile.TemporaryDirectory(prefix="fota_checkpoint_") as td:
        t = Path(td)
        sources = [ROOT / "src/fota_checkpoint.c", ROOT / "src/crc32.c"]
        if fota:
            stubs = {
                "config.h": '#ifndef CONFIG_H\n#define CONFIG_H\n#include <stdint.h>\nextern volatile uint32_t g_tick_ms;\n#define TICK_MS() g_tick_ms\n#define CFG_IP_LEN 64\ntypedef struct {uint32_t fota_size;} config_t;\nconst config_t *cfg_get(void);\n#endif\n',
                "flash_config.h": '#include "config.h"\n',
                "ec800m.h": '#include <stdint.h>\n#define EC800M_CH_OTA 1\nint ec800m_tcp_open(int,const char*,uint16_t);\nvoid ec800m_tcp_send(int,const uint8_t*,uint16_t);\nvoid ec800m_tcp_close(int);\n',
                "debug_uart.h": "",
                "hw_init.h": 'void delay_ms(unsigned);\n',
                "n32l40x.h": 'void NVIC_SystemReset(void);\n',
            }
            for filename, text in stubs.items():
                (t / filename).write_text(text, encoding="ascii")
            sources += [ROOT / "src/fota.c", ROOT / "src/service_workspace.c"]
        harness = t / "harness.c"
        harness.write_text(source, encoding="ascii")
        exe = t / (name + ".exe")
        cmd = [cc, "-std=c99", "-O1", "-Wall", "-Wextra", "-Werror", "-I", str(t),
               "-I", str(ROOT / "include"), *map(str, sources), str(harness), "-o", str(exe)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        result = subprocess.run([str(exe)], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        print(result.stdout.strip())


def test_checkpoint_powercuts():
    assert (ROOT / "include/fota_checkpoint.h").exists(), "dual-slot checkpoint API missing"
    run_host(NOR + r'''
static uint8_t baseline[8192];
static fota_checkpoint_t input, output;
static void cut_commit(void){if(setjmp(reset)==0)(void)fota_checkpoint_commit(&input);cut=-1;}
static void cut_clear(void){if(setjmp(reset)==0)(void)fota_checkpoint_clear();cut=-1;}
static void seed(uint32_t seq,uint32_t offset){
    input.offset=offset;input.sequence=seq;
    input.magic=FOTA_CHECKPOINT_MAGIC;input.format_version=FOTA_CHECKPOINT_FORMAT;
    input.record_length=sizeof input;input.commit_marker=FOTA_CHECKPOINT_MARKER;
    input.crc32=crc32_compute(&input,offsetof(fota_checkpoint_t,crc32));
    memcpy(flash+0x102000,&input,sizeof input);
}
int main(void){
    unsigned scenarios=0;int count;
    assert(FOTA_CHECKPOINT_SLOT_A==0x102000 && FOTA_CHECKPOINT_SLOT_B==0x103000);
    memset(flash,255,sizeof flash);memset(&input,0,sizeof input);
    strcpy(input.url,"http://example.invalid/a.bin");strcpy(input.etag,"v7");
    input.expected_length=24577;input.version=7;input.running_crc=0;
    assert(!fota_checkpoint_load(input.url,input.expected_length,&output));
    assert(fota_checkpoint_commit(&input));assert(body_writes==1 && marker_writes==1);
    assert(full_reads>=3);
    for(unsigned generation=1;generation<=4;generation++){
        assert(fota_checkpoint_load(input.url,24577,&output));
        uint32_t previous=output.offset;input.offset=generation*4096;
        memcpy(baseline,flash+0x102000,sizeof baseline);
        steps=0;cut=1000000;erase_count=0;assert(fota_checkpoint_commit(&input));count=steps;cut=-1;
        assert(erase_count==1);assert(erased[0]==(generation%2?0x103000:0x102000));
        for(int point=0;point<=count;point++){
            memcpy(flash+0x102000,baseline,sizeof baseline);erase_count=0;steps=0;cut=point;
            cut_commit();
            assert(fota_checkpoint_load(input.url,24577,&output));
            assert(output.offset==previous || output.offset==input.offset);
            if(point%127==0){
                uint32_t at_least=output.offset;erase_count=0;steps=0;cut=777;
                cut_commit();
                assert(fota_checkpoint_load(input.url,24577,&output));assert(output.offset>=at_least);
            }
            ++scenarios;
        }
        memcpy(flash+0x102000,baseline,sizeof baseline);
        erase_count=0;assert(fota_checkpoint_commit(&input));
    }
    assert(!fota_checkpoint_load("other",24577,&output));
    assert(!fota_checkpoint_load(input.url,24578,&output));
    locked=EXT_FLASH_OWNER_CONFIG;assert(!fota_checkpoint_commit(&input));
    assert(!fota_checkpoint_load(input.url,24577,&output));assert(!fota_checkpoint_clear());locked=EXT_FLASH_OWNER_OTA;
    erase_count=0;fail_read=1;assert(!fota_checkpoint_commit(&input));assert(erase_count==0);fail_read=0;
    memset(flash+0x102000,255,8192);erase_count=0;assert(fota_checkpoint_commit(&input));
    memcpy(baseline,flash+0x102000,8192);
    for(unsigned i=0;i<sizeof input;i++){
        memcpy(flash+0x102000,baseline,8192);flash[0x102000+i]^=1;
        assert(!fota_checkpoint_load(input.url,24577,&output));
    }
    memcpy(flash+0x102000,baseline,8192);input.offset=1;assert(!fota_checkpoint_commit(&input));
    input.offset=28672;assert(!fota_checkpoint_commit(&input));
    input.offset=4096;memset(input.url,'x',sizeof input.url);assert(!fota_checkpoint_commit(&input));
    strcpy(input.url,"http://example.invalid/a.bin");
    memset(flash+0x102000,255,8192);seed(0xfffffffeU,4096);
    for(unsigned i=0;i<3;i++){
        input.offset+=4096;erase_count=0;assert(fota_checkpoint_commit(&input));
        assert(fota_checkpoint_load(input.url,24577,&output));assert(output.offset==input.offset);
        assert(output.sequence==(uint32_t)(0xffffffffU+i));
    }
    /* Clear is also journaled: every cut leaves the previous record or an
       authoritative tombstone, never a stale predecessor after success. */
    memcpy(baseline,flash+0x102000,8192);
    erase_count=0;steps=0;cut=1000000;assert(fota_checkpoint_clear());count=steps;cut=-1;
    for(int point=0;point<=count;point++){
        memcpy(flash+0x102000,baseline,8192);erase_count=0;steps=0;cut=point;
        cut_clear();
        if(fota_checkpoint_load(input.url,24577,&output))assert(output.offset==input.offset);
        ++scenarios;
    }
    memcpy(flash+0x102000,baseline,8192);marker_writes=0;corrupt_final=1;erase_count=0;
    assert(!fota_checkpoint_commit(&input));corrupt_final=0;
    assert(fota_checkpoint_load(input.url,24577,&output));assert(output.offset==input.offset);
    erase_count=0;assert(fota_checkpoint_clear());assert(!fota_checkpoint_load(input.url,24577,&output));
    erase_count=0;assert(fota_checkpoint_clear());assert(!fota_checkpoint_load(input.url,24577,&output));
    printf("checkpoint: %u byte-cut scenarios, repeated cuts, 4 replacements, wrap, CRC, ownership, clear PASS\n",scenarios);
    return 0;
}
''', "powercut")


def test_authorization_powercuts():
    run_host(NOR + r'''
static uint8_t baseline[8192];
static fota_authorization_t input, output;
static void cut_commit(void){if(setjmp(reset)==0)(void)fota_authorization_commit(&input);cut=-1;}
int main(void){
    int count; unsigned scenarios=0;
    memset(flash,255,sizeof flash);memset(&input,0,sizeof input);
    input.package_length=4097;input.package_version=3002;
    input.target_address=0x08006000;input.signing_key_id=1;
    for(unsigned i=0;i<32;i++)input.package_sha256[i]=(uint8_t)i;
    for(unsigned i=0;i<64;i++)input.signature[i]=(uint8_t)(0x80+i);
    assert(FOTA_AUTH_SLOT_A==0x104000 && FOTA_AUTH_SLOT_B==0x105000);
    assert(!fota_authorization_load(&output));
    assert(fota_authorization_commit(&input));
    assert(fota_authorization_load(&output));
    assert(output.package_length==input.package_length);
    assert(!memcmp(output.package_sha256,input.package_sha256,32));
    assert(!memcmp(output.signature,input.signature,64));
    memcpy(baseline,flash+FOTA_AUTH_SLOT_A,8192);
    input.package_length=8193;input.package_sha256[0]^=0x55;
    steps=0;cut=1000000;assert(fota_authorization_commit(&input));count=steps;cut=-1;
    for(int point=0;point<=count;point++){
        memcpy(flash+FOTA_AUTH_SLOT_A,baseline,8192);erase_count=0;steps=0;cut=point;cut_commit();
        assert(fota_authorization_load(&output));
        assert(output.package_length==4097 || output.package_length==8193);
        ++scenarios;
    }
    printf("authorization: %u byte-cut scenarios PASS\n",scenarios);return 0;
}
''', "authorization")


if __name__ == "__main__":
    test_checkpoint_powercuts()
    test_authorization_powercuts()
    print("test_fota_checkpoint_powercut: PASS")
