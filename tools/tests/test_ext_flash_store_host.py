import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).parents[2]

def _compiler():
    return shutil.which("gcc") or shutil.which("clang") or shutil.which("cc")

def test_fota_failed_lock_does_not_unlock_owner():
    cc = _compiler()
    if not cc:
        return
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "spi_flash.h").write_text("""#ifndef SPI_FLASH_H
#define SPI_FLASH_H
#include <stdint.h>
#include <stdbool.h>
#define FLASH_TOTAL_SIZE (2U*1024U*1024U)
#define FLASH_SECTOR_SIZE 4096U
bool spi_flash_read(uint32_t, uint8_t *, uint32_t);
bool spi_flash_write(uint32_t, const uint8_t *, uint32_t);
bool spi_flash_erase_sector(uint32_t);
#endif
""", encoding="utf-8")
        (t / "ext_flash_layout.h").write_text("""#ifndef EXT_FLASH_LAYOUT_H
#define EXT_FLASH_LAYOUT_H
#include "spi_flash.h"
#define EXT_FLASH_RESUME_ADDR 0x100000UL
#endif
""", encoding="utf-8")
        (t / "ext_flash_store.h").write_text("""#include <stdint.h>
#include <stdbool.h>
typedef enum { EXT_FLASH_OWNER_NONE=0, EXT_FLASH_OWNER_OTA, EXT_FLASH_OWNER_AGNSS, EXT_FLASH_OWNER_BLIND_ZONE, EXT_FLASH_OWNER_CONFIG } ext_flash_owner_t;
bool ext_flash_try_lock(ext_flash_owner_t); void ext_flash_unlock(ext_flash_owner_t);
bool ext_flash_read(ext_flash_owner_t, uint32_t, void *, uint32_t);
bool ext_flash_write_verified(ext_flash_owner_t, uint32_t, const void *, uint32_t);
bool ext_flash_erase(ext_flash_owner_t, uint32_t, uint32_t);
""", encoding="utf-8")
        (t / "config.h").write_text("""#ifndef CONFIG_H
#define CONFIG_H
#include <stdint.h>
extern volatile uint32_t g_tick_ms;
#define TICK_MS() g_tick_ms
#define SPI_FLASH_TIMEOUT_MS 2U
#define CFG_IP_LEN 64
typedef struct { uint32_t fota_size; } config_t;
const config_t *cfg_get(void);
#endif
""", encoding="utf-8")
        (t / "flash_config.h").write_text(
            """#ifndef FLASH_CONFIG_H
#define FLASH_CONFIG_H
#include "config.h"
#include "ext_flash_layout.h"
#endif
""",
            encoding="utf-8",
        )
        (t / "fota.h").write_text("""#ifndef FOTA_H
#define FOTA_H
#include <stdint.h>
#include <stdbool.h>
#define FOTA_FLASH_ADDR 0x10000U
#define FOTA_MAX_SIZE 0x1000U
#define FOTA_RESUME_MAGIC 0x46525331UL
typedef struct { const char *url; uint32_t expected_length; const char *etag; uint32_t version; } fota_request_t;
typedef enum { FOTA_STATE_IDLE=0, FOTA_STATE_CONNECTING, FOTA_STATE_DOWNLOADING, FOTA_STATE_VERIFYING, FOTA_STATE_READY, FOTA_STATE_ERROR } fota_state_t;
typedef struct { fota_state_t state; uint32_t offset; uint32_t expected_length; uint32_t crc32; uint8_t resumable; char url[128]; char etag[40]; } fota_status_t;
void fota_init(void); int fota_start(const char *); void fota_on_http_header(const char *); void fota_on_chunk(const uint8_t *, uint16_t, uint32_t);
#endif
""", encoding="utf-8")
        for name, body in {
            "ec800m.h": "#include <stdint.h>\n#define EC800M_CH_OTA 1\nint ec800m_tcp_open(int, const char *, uint16_t);\nvoid ec800m_tcp_send(int, const uint8_t *, uint16_t);\n",
            "debug_uart.h": "void dbg_printf(const char *, ...);\n",
            "hw_init.h": "void delay_ms(unsigned);\n",
            "n32l40x.h": "void NVIC_SystemReset(void);\n",
        }.items():
            (t / name).write_text(body, encoding="utf-8")
        (t / "harness.c").write_text("""#include <assert.h>
#include <string.h>
#include "config.h"
#include "ext_flash_layout.h"
#include "fota.h"
#include "ext_flash_store.h"
#include "bcr.h"
volatile uint32_t g_tick_ms; static const config_t cfg = { 0 };
const config_t *cfg_get(void) { return &cfg; }
bool bcr_valid(const bcr_record_t *r) { (void)r; return false; }
bool spi_flash_read(uint32_t a,uint8_t *b,uint32_t n){memset(b,0xff,n);return a+n<=FLASH_TOTAL_SIZE;}
bool spi_flash_write(uint32_t a,const uint8_t *b,uint32_t n){(void)b;return a+n<=FLASH_TOTAL_SIZE;}
bool spi_flash_erase_sector(uint32_t a){return a<FLASH_TOTAL_SIZE&&!(a%FLASH_SECTOR_SIZE);}
int ec800m_tcp_open(int c,const char *h,uint16_t p){(void)c;(void)h;(void)p;return -1;}
void ec800m_tcp_send(int c,const uint8_t *p,uint16_t n){(void)c;(void)p;(void)n;}
void dbg_printf(const char *f,...){(void)f;} void delay_ms(unsigned m){(void)m;} void NVIC_SystemReset(void){}
int main(void){assert(ext_flash_try_lock(EXT_FLASH_OWNER_CONFIG));assert(fota_start("http://example.invalid/fw.bin")<0);assert(!ext_flash_try_lock(EXT_FLASH_OWNER_OTA));ext_flash_unlock(EXT_FLASH_OWNER_CONFIG);assert(ext_flash_try_lock(EXT_FLASH_OWNER_OTA));ext_flash_unlock(EXT_FLASH_OWNER_OTA);return 0;}
""", encoding="utf-8")
        exe=t/"fota_lock_test.exe"
        subprocess.run([cc,"-std=c99","-I",str(t),"-I",str(ROOT/"bootloader"/"include"),str(ROOT/"src"/"ext_flash_store.c"),str(ROOT/"src"/"fota.c"),str(t/"harness.c"),"-o",str(exe)],check=True,capture_output=True,text=True)
        subprocess.run([str(exe)],check=True,capture_output=True,text=True)

def test_owner_bounds_alignment_and_error_propagation():
    cc = _compiler()
    if not cc:
        return
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "spi_flash.h").write_text("""#ifndef SPI_FLASH_H
#define SPI_FLASH_H
#include <stdint.h>
#include <stdbool.h>
#define FLASH_PAGE_SIZE 256
#define FLASH_SECTOR_SIZE 4096
#define FLASH_TOTAL_SIZE (2*1024*1024)
bool spi_flash_read(uint32_t,uint8_t*,uint32_t);
bool spi_flash_write(uint32_t,const uint8_t*,uint32_t);
bool spi_flash_erase_sector(uint32_t);
#endif
""", encoding="utf-8")
        (t / "config.h").write_text("#include <stdint.h>\nextern volatile uint32_t g_tick_ms;\nuint32_t test_tick_read(void);\n#define TICK_MS() test_tick_read()\n#define SPI_FLASH_TIMEOUT_MS 2U\n", encoding="utf-8")
        (t / "ext_flash_layout.h").write_text("""#include <stdint.h>
#include "spi_flash.h"
typedef enum { EXT_FLASH_OWNER_NONE=0, EXT_FLASH_OWNER_OTA, EXT_FLASH_OWNER_AGNSS, EXT_FLASH_OWNER_BLIND_ZONE, EXT_FLASH_OWNER_CONFIG } ext_flash_owner_t;
""", encoding="utf-8")
        (t / "ext_flash_store.h").write_text("""#include <stdint.h>
#include <stdbool.h>
#include "ext_flash_layout.h"
bool ext_flash_read(ext_flash_owner_t,uint32_t,void*,uint32_t);
bool ext_flash_write_verified(ext_flash_owner_t,uint32_t,const void*,uint32_t);
bool ext_flash_erase(ext_flash_owner_t,uint32_t,uint32_t);
bool ext_flash_try_lock(ext_flash_owner_t);
bool ext_flash_try_lock_now(ext_flash_owner_t);
void ext_flash_unlock(ext_flash_owner_t);
""", encoding="utf-8")
        (t / "harness.c").write_text("""#include <assert.h>
#include <stdint.h>
#include <string.h>
#include "ext_flash_store.h"
volatile uint32_t g_tick_ms; static unsigned tick_reads;
uint32_t test_tick_read(void){++tick_reads;return g_tick_ms;}
static int fail_write;
bool spi_flash_read(uint32_t a,uint8_t*b,uint32_t n){ memset(b,0x5a,n); return a+n<=FLASH_TOTAL_SIZE; }
bool spi_flash_write(uint32_t a,const uint8_t*b,uint32_t n){ (void)b; return !fail_write && a+n<=FLASH_TOTAL_SIZE; }
bool spi_flash_erase_sector(uint32_t a){ return a<FLASH_TOTAL_SIZE && !(a%FLASH_SECTOR_SIZE); }
int main(void){ uint8_t b[4],d[4]={1,2,3,4}; assert(ext_flash_try_lock(EXT_FLASH_OWNER_CONFIG)); tick_reads=0; assert(!ext_flash_try_lock(EXT_FLASH_OWNER_OTA)); assert(tick_reads>0); tick_reads=0; assert(!ext_flash_try_lock_now(EXT_FLASH_OWNER_BLIND_ZONE)); assert(tick_reads==0); assert(!ext_flash_read(EXT_FLASH_OWNER_OTA,0,b,1)); assert(ext_flash_read(EXT_FLASH_OWNER_CONFIG,0,b,1)); assert(!ext_flash_erase(EXT_FLASH_OWNER_CONFIG,1,FLASH_SECTOR_SIZE)); assert(ext_flash_erase(EXT_FLASH_OWNER_CONFIG,0,FLASH_SECTOR_SIZE)); fail_write=1; assert(!ext_flash_write_verified(EXT_FLASH_OWNER_CONFIG,0,d,sizeof d)); ext_flash_unlock(EXT_FLASH_OWNER_CONFIG); assert(ext_flash_try_lock(EXT_FLASH_OWNER_OTA)); ext_flash_unlock(EXT_FLASH_OWNER_OTA); return 0;}
""", encoding="utf-8")
        exe = t / "host_test.exe"
        cmd = [cc, "-std=c99", "-I", str(t), str(ROOT / "src" / "ext_flash_store.c"), str(t / "harness.c"), "-o", str(exe)]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        subprocess.run([str(exe)], check=True, capture_output=True, text=True)

if __name__ == "__main__":
    test_fota_failed_lock_does_not_unlock_owner()
    test_owner_bounds_alignment_and_error_propagation()
    print("test_ext_flash_store_host: PASS")
