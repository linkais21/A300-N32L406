"""Execute real AGNSS storage/manager against NOR; count payload I/O."""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HARNESS = r'''
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <stddef.h>
#include <string.h>
#include "agnss_storage.h"
#include "agnss_manager.h"
#include "agnss_vendor.h"
#include "ext_flash_store.h"
#include "service_workspace.h"
#include "fota.h"
#include "crc32.h"

uint32_t tick;
void agnss_online_reset(void){}
bool agnss_online_process(gnss_type_t t){(void)t;return false;}
bool agnss_online_has_injected(void){return false;}
static uint8_t flash[FLASH_TOTAL_SIZE], payload[AGNSS_MAX_DATA];
static uint32_t payload_reads, output_len, expected_len;
static const uint8_t *expected;
static bool fail_read, fail_write, fail_erase, fail_callback;
static uint32_t write_budget=UINT32_MAX, fail_read_at=UINT32_MAX;
static unsigned completed;
static char last_log[128];
static fota_state_t ota_state;
int dbg_printf(const char *fmt,...){va_list args;va_start(args,fmt);int n=vsnprintf(last_log,sizeof last_log,fmt,args);va_end(args);return n;}

bool spi_flash_read(uint32_t a,uint8_t *b,uint32_t n) {
    assert(a <= sizeof flash && n <= sizeof flash-a);
    if(fail_read || a==fail_read_at) return false;
    if(a >= EXT_FLASH_AGNSS_SLOT_A_ADDR) payload_reads += n;
    memcpy(b,flash+a,n); return true;
}
bool spi_flash_write(uint32_t a,const uint8_t *b,uint32_t n) {
    assert(a <= sizeof flash && n <= sizeof flash-a);
    for(uint32_t i=0;i<n;i++) {
        if(write_budget==0)return false;
        if(write_budget!=UINT32_MAX)write_budget--;
        if(fail_write && i==n/2) return false;
        assert((flash[a+i]&b[i])==b[i]); flash[a+i]&=b[i];
    }
    return true;
}
spi_flash_program_result_t spi_flash_write_result(uint32_t a,const uint8_t*b,uint32_t n) {
    return spi_flash_write(a,b,n)?SPI_FLASH_PROGRAM_COMPLETED:SPI_FLASH_PROGRAM_ISSUED_UNCERTAIN;
}
bool spi_flash_erase_sector(uint32_t a) {
    assert(a%FLASH_SECTOR_SIZE==0 && a+FLASH_SECTOR_SIZE<=sizeof flash);
    if(fail_erase)return false;
    memset(flash+a,255,FLASH_SECTOR_SIZE);return true;
}
void spi_flash_note_verify_failure(void) {}
fota_state_t fota_get_state(void){return ota_state;}
bool ec800m_is_ready(void){return true;}
bool gps_is_valid(void){return false;}
void gnss_vendor_set_type(gnss_type_t t){(void)t;}
bool gnss_vendor_inject_pending(void){return false;}
bool gnss_vendor_inject(gnss_type_t t,const uint8_t*p,uint16_t n) {
    assert(t==GNSS_TYPE_TAU804M);
    if(fail_callback)return false;
    if(!n){assert(output_len==expected_len);completed++;return true;}
    assert(output_len+n<=expected_len);
    assert(memcmp(p,expected+output_len,n)==0);
    output_len+=n;return true;
}
static void reset(void) {
    agnss_storage_abort();
    memset(flash,255,sizeof flash);
    for(uint32_t i=0;i<sizeof payload;i++)payload[i]=(uint8_t)(i*17+i/256);
    tick=1;fail_read=fail_write=fail_erase=fail_callback=false;
    write_budget=fail_read_at=UINT32_MAX;
    output_len=completed=payload_reads=0;ota_state=FOTA_STATE_IDLE;
    agnss_init(GNSS_TYPE_TAU804M);
    expected=payload;
}
static void put(uint8_t slot,uint32_t seq,uint32_t length) {
    agnss_meta_t m={0};m.type=GNSS_TYPE_TAU804M;m.sequence=seq;m.length=length;
    assert(agnss_storage_begin(slot));
    for(uint32_t o=0;o<length;) {
        uint16_t n=length-o>1024?1024:(uint16_t)(length-o);
        assert(agnss_storage_write(payload+o,n));o+=n;
    }
    assert(agnss_storage_commit(&m));
}
static void injection(uint32_t length,bool dual) {
    reset();expected_len=length;
    put(0,1,length);if(dual)put(1,2,length);
    payload_reads=0;
    for(uint32_t i=0;i<(length+1023)/1024+1;i++)agnss_process();
    assert(completed==1 && output_len==length && agnss_has_injected());
    assert(strstr(last_log,"[AGNSS-CACHE] tx_done=1")&&strstr(last_log,"bytes="));
    printf("length=%u slots=%u payload_reads=%u budget=%u\n",
           (unsigned)length,dual?2:1,(unsigned)payload_reads,(unsigned)(length*(dual?3:2)));
    fflush(stdout);
    assert(payload_reads<=length*(dual?3:2));
}
static void lifecycle(void) {
    agnss_meta_t m;
    uint8_t buf[1025];
    reset();put(0,1,4097);
    assert(!agnss_storage_read_chunk(0,buf,1));
    assert(!agnss_storage_read_open(NULL));
    assert(agnss_storage_read_open(&m));
    assert(m.sequence==1 && m.length==4097);
    payload_reads=0;
    assert(agnss_storage_read_chunk(4096,buf,1) && buf[0]==payload[4096]);
    assert(agnss_storage_read_chunk(0,buf,1024) && !memcmp(buf,payload,1024));
    assert(payload_reads==1025);
    const uint32_t offsets[]={4098,4097,UINT32_MAX,0,0};
    const uint16_t lengths[]={0,1,1,1025,1};
    for(unsigned i=0;i<5;i++) {
        assert(agnss_storage_read_open(&m));
        assert(!agnss_storage_read_chunk(offsets[i],i==4?NULL:buf,lengths[i]));
        assert(!agnss_storage_read_chunk(0,buf,1));
    }
    assert(agnss_storage_read_open(&m));
    assert(agnss_storage_read_chunk(4097,buf,0));
    agnss_storage_read_close();agnss_storage_read_close();
    payload_reads=0;assert(agnss_storage_read_open(&m));assert(payload_reads==4097);

    /* Independent callers cannot redirect the pinned slot or bypass hashing. */
    payload_reads=0;assert(agnss_storage_read(0,buf,1));assert(payload_reads==4098);
    assert(agnss_storage_get_latest(&m));
    assert(agnss_storage_read_chunk(0,buf,1));
    agnss_storage_abort();assert(!agnss_storage_read_chunk(0,buf,1));
    assert(agnss_storage_read_open(&m));
    assert(agnss_storage_init());assert(!agnss_storage_read_chunk(0,buf,1));
    assert(agnss_storage_read_open(&m));
    assert(!agnss_storage_begin(2));assert(!agnss_storage_read_chunk(0,buf,1));
    assert(agnss_storage_read_open(&m));
    assert(agnss_storage_begin(1));assert(!agnss_storage_read_open(&m));
    assert(!agnss_storage_read_chunk(0,buf,1));
    assert(agnss_storage_init()); /* reset releases only its own write lock */
    assert(ext_flash_try_lock(EXT_FLASH_OWNER_OTA));ext_flash_unlock(EXT_FLASH_OWNER_OTA);
    assert(agnss_storage_read_open(&m));
    put(1,2,2049);assert(!agnss_storage_read_chunk(0,buf,1));
    assert(agnss_storage_read_open(&m) && m.sequence==2 && m.length==2049);
    assert(agnss_storage_read_chunk(2048,buf,1) && buf[0]==payload[2048]);
}
static void owners_and_failures(void) {
    agnss_meta_t m;uint8_t b;
    reset();put(0,1,4097);
    assert(ext_flash_try_lock(EXT_FLASH_OWNER_OTA));
    assert(!agnss_storage_read_open(&m));
    assert(!ext_flash_try_lock_now(EXT_FLASH_OWNER_BLIND_ZONE));
    ext_flash_unlock(EXT_FLASH_OWNER_OTA);
    assert(service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_OTA));
    assert(!agnss_storage_read_open(&m));
    assert(!service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_DIAGNOSTIC));
    service_workspace_release(SERVICE_WORKSPACE_OWNER_OTA);
    assert(agnss_storage_read_open(&m));
    assert(ext_flash_try_lock(EXT_FLASH_OWNER_OTA));
    assert(!agnss_storage_read_chunk(0,&b,1));
    assert(!ext_flash_try_lock_now(EXT_FLASH_OWNER_BLIND_ZONE));
    ext_flash_unlock(EXT_FLASH_OWNER_OTA);
    assert(agnss_storage_read_open(&m));
    assert(service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_OTA));
    assert(!agnss_storage_read_chunk(0,&b,1));
    assert(!service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_DIAGNOSTIC));
    service_workspace_release(SERVICE_WORKSPACE_OWNER_OTA);
    assert(agnss_storage_read_open(&m));
    fail_read=true;assert(!agnss_storage_read_chunk(0,&b,1));fail_read=false;
    assert(!agnss_storage_read_chunk(0,&b,1));
    assert(agnss_storage_read_open(&m));
    fail_read_at=EXT_FLASH_AGNSS_SLOT_A_ADDR;
    assert(!agnss_storage_read_chunk(0,&b,1));
    fail_read_at=UINT32_MAX;
    assert(!agnss_storage_read_chunk(0,&b,1));
    assert(agnss_storage_read_open(&m));
    fail_erase=true;assert(!agnss_storage_begin(1));fail_erase=false;
    assert(!agnss_storage_read_chunk(0,&b,1));
    assert(agnss_storage_read_open(&m));
    assert(agnss_storage_begin(1));fail_write=true;
    assert(!agnss_storage_write(payload,1024));fail_write=false;
    assert(agnss_storage_read_open(&m) && m.sequence==1);
    assert(agnss_storage_begin(1));assert(agnss_storage_write(payload,1024));
    m.length=1024;m.sequence=2;fail_write=true;
    assert(!agnss_storage_commit(&m));fail_write=false;
    assert(agnss_storage_init());
    assert(agnss_storage_read_open(&m) && m.sequence==1);
}
static void commit_cut_points(void) {
    for(unsigned cut=0;cut<=sizeof(agnss_meta_t);cut++) {
        agnss_meta_t m={0};
        reset();put(0,1,1024);assert(agnss_storage_read_open(&m));
        assert(agnss_storage_begin(1));assert(agnss_storage_write(payload,1024));
        m.sequence=2;write_budget=cut;
        assert(agnss_storage_commit(&m)==(cut==sizeof m));
        write_budget=UINT32_MAX;assert(agnss_storage_init());
        assert(agnss_storage_read_open(&m));
        assert(m.sequence==(cut==sizeof m?2U:1U));
    }
}
static void corruptions(void) {
    agnss_meta_t m;uint8_t b;
    reset();put(0,1,4097);put(1,2,4097);
    flash[EXT_FLASH_AGNSS_SLOT_B_ADDR+100]^=1;
    assert(agnss_storage_read_open(&m) && m.sequence==1);
    agnss_storage_read_close();
    flash[EXT_FLASH_AGNSS_SLOT_A_ADDR+100]^=1;
    assert(!agnss_storage_read_open(&m));

    /* Correct payload CRC with a stale SHA must still be rejected. */
    memcpy(&m,flash+EXT_FLASH_AGNSS_META_ADDR,sizeof m);
    m.crc32=crc32_compute(flash+EXT_FLASH_AGNSS_SLOT_A_ADDR,m.length);
    m.metadata_crc=crc32_compute((const uint8_t*)&m,offsetof(agnss_meta_t,metadata_crc));
    memcpy(flash+EXT_FLASH_AGNSS_META_ADDR,&m,sizeof m);
    assert(!agnss_storage_read_open(&m));

    reset();put(0,1,4097);assert(agnss_storage_read_open(&m));
    flash[EXT_FLASH_AGNSS_META_ADDR+offsetof(agnss_meta_t,commit_marker)]^=1;
    assert(!agnss_storage_read_chunk(0,&b,1));
    assert(!agnss_storage_read_open(&m));
    reset();put(0,1,4097);assert(agnss_storage_read_open(&m));
    agnss_storage_read_close();flash[EXT_FLASH_AGNSS_SLOT_A_ADDR]^=1;
    assert(!agnss_storage_read_open(&m));

    /* Preserve existing unsigned numeric sequence ordering, including wrap. */
    reset();put(0,UINT32_MAX,1);put(1,0,1);
    assert(agnss_storage_read_open(&m) && m.sequence==UINT32_MAX);
}
static void manager_retry_refresh(void) {
    reset();expected_len=4097;put(0,1,expected_len);
    fail_callback=true;agnss_process();assert(output_len==0);
    fail_callback=false;payload_reads=0;
    tick+=59999;agnss_process();assert(payload_reads==0);
    tick++;agnss_process();assert(output_len==1024 && payload_reads==5121);
    ota_state=FOTA_STATE_DOWNLOADING;agnss_process();assert(output_len==1024);
    ota_state=FOTA_STATE_IDLE;
    for(unsigned i=0;i<5;i++)agnss_process();
    assert(completed==1 && output_len==4097);
    tick+=2UL*60*60*1000;output_len=0;payload_reads=0;
    for(unsigned i=0;i<6;i++)agnss_process();
    assert(completed==2 && output_len==4097 && payload_reads==8194);
    /* A subsequent session revalidates even when metadata is unchanged. */
    tick+=2UL*60*60*1000;flash[EXT_FLASH_AGNSS_SLOT_A_ADDR]^=1;
    output_len=0;agnss_process();assert(output_len==0 && completed==2);
}
static void manager_replacement_and_late_retry(void) {
    reset();expected_len=4097;put(0,1,expected_len);
    agnss_process();assert(output_len==1024);
    /* Replace the active slot with the same sequence/length, different CRC. */
    for(unsigned i=0;i<expected_len;i++)payload[i]^=0x55;
    put(0,1,expected_len);output_len=0;
    agnss_process();assert(output_len==1024);
    fail_callback=true;agnss_process();assert(output_len==1024);
    fail_callback=false;tick+=60000;payload_reads=0;
    agnss_process();assert(output_len==2048 && payload_reads==5121);
    for(unsigned i=0;i<3;i++)agnss_process();
    assert(output_len==4097 && completed==0);
    fail_callback=true;agnss_process();assert(completed==0);
    fail_callback=false;tick+=60000;payload_reads=0;
    agnss_process();assert(completed==1 && payload_reads==4097);
    agnss_process();assert(completed==1);
}
int main(void) {
    injection(4097,false);
    injection(4097,true);
    injection(AGNSS_MAX_DATA,false);
    injection(0,false);
    lifecycle();owners_and_failures();corruptions();manager_retry_refresh();
    manager_replacement_and_late_retry();
    commit_cut_points();
    return 0;
}
'''


def test_snapshot_io_and_lifecycle():
    cc = shutil.which("gcc") or shutil.which("clang")
    assert cc, "host C compiler required"
    with tempfile.TemporaryDirectory(prefix="agnss_snapshot_") as directory:
        temp = Path(directory)
        (temp / "config.h").write_text(
            '#include <stdint.h>\nextern uint32_t tick;\n#define TICK_MS() tick\n', encoding="ascii")
        (temp / "harness.c").write_text(HARNESS, encoding="ascii")
        exe = temp / "snapshot.exe"
        command = [cc, "-std=c99", "-Wall", "-Wextra", "-Werror", "-DSPI_FLASH_TIMEOUT_MS=0U",
                   "-Wno-type-limits", "-I", str(temp), "-I", str(ROOT / "include"),
                   str(temp / "harness.c")]
        command += [str(ROOT / "src" / name) for name in (
            "agnss_storage.c", "sha256.c", "agnss_manager.c", "ext_flash_store.c",
            "service_workspace.c", "crc32.c")]
        built = subprocess.run(command + ["-o", str(exe)], capture_output=True, text=True)
        assert built.returncode == 0, built.stderr
        run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
        print(run.stdout, end="")
        assert run.returncode == 0, run.stderr


if __name__ == "__main__":
    test_snapshot_io_and_lifecycle()
    print("test_agnss_snapshot: PASS")
