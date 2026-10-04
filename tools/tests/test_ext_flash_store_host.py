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
typedef enum { SPI_FLASH_PROGRAM_NOT_ISSUED=0, SPI_FLASH_PROGRAM_ISSUED_UNCERTAIN, SPI_FLASH_PROGRAM_COMPLETED } spi_flash_program_result_t;
bool spi_flash_read(uint32_t, uint8_t *, uint32_t);
bool spi_flash_write(uint32_t, const uint8_t *, uint32_t);
spi_flash_program_result_t spi_flash_write_result(uint32_t,const uint8_t*,uint32_t);
bool spi_flash_erase_sector(uint32_t);
void spi_flash_note_verify_failure(void);
#endif
""", encoding="utf-8")
        (t / "ext_flash_layout.h").write_text(
            (ROOT / "include/ext_flash_layout.h").read_text(encoding="utf-8"), encoding="utf-8")
        (t / "ext_flash_store.h").write_text("""#include <stdint.h>
#include <stdbool.h>
#include "ext_flash_layout.h"
bool ext_flash_try_lock(ext_flash_owner_t); void ext_flash_unlock(ext_flash_owner_t);
bool ext_flash_try_lock_now(ext_flash_owner_t);
bool ext_flash_read(ext_flash_owner_t, uint32_t, void *, uint32_t);
bool ext_flash_write_verified(ext_flash_owner_t, uint32_t, const void *, uint32_t);
typedef enum { EXT_FLASH_PROGRAM_NOT_ISSUED=0, EXT_FLASH_PROGRAM_ISSUED_UNCERTAIN, EXT_FLASH_PROGRAM_VERIFIED } ext_flash_program_result_t;
ext_flash_program_result_t ext_flash_write_result(ext_flash_owner_t,uint32_t,const void*,uint32_t);
bool ext_flash_erase(ext_flash_owner_t, uint32_t, uint32_t);
""", encoding="utf-8")
        (t / "boot_contract.h").write_text((ROOT / "include" / "boot_contract.h").read_text(encoding="utf-8"), encoding="utf-8")
        (t / "firmware_layout.h").write_text((ROOT / "include" / "firmware_layout.h").read_text(encoding="utf-8"), encoding="utf-8")
        (t / "crc32.h").write_text((ROOT / "include" / "crc32.h").read_text(encoding="utf-8"), encoding="utf-8")
        (t / "firmware_signature.h").write_text("#include <stdint.h>\n#include <stdbool.h>\nbool firmware_signature_verify(const uint8_t*,const uint8_t*);\n", encoding="utf-8")
        (t / "config.h").write_text("""#ifndef CONFIG_H
#define CONFIG_H
#include <stdint.h>
extern volatile uint32_t g_tick_ms;
#define TICK_MS() g_tick_ms
#define SPI_FLASH_TIMEOUT_MS 2U
#define CFG_IP_LEN 64
#define CFG_DEVICE_API_KEY_LEN 32U
typedef struct {
    uint32_t fota_size;
    const char *fota_url;
    const char *device_api_key;
} config_t;
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
        # Keep the fixture's OTA API synchronized with the production header;
        # the implementation now uses the authenticated check/preparation
        # states added by the HTTP OTA integration.
        (t / "fota.h").write_text(
            (ROOT / "include/fota.h").read_text(encoding="utf-8"), encoding="utf-8")
        for name, body in {
            "ec800m.h": "#include <stdint.h>\n#include <stdbool.h>\n#define EC800M_CH_OTA 1\ntypedef enum { TCP_STATE_CLOSED=0, TCP_STATE_OPENING, TCP_STATE_OPEN, TCP_STATE_ERROR } tcp_state_t;\nint ec800m_tcp_open(int, const char *, uint16_t);\nint ec800m_tcp_send(int, const uint8_t *, uint16_t);\nvoid ec800m_tcp_close(int);\ntcp_state_t ec800m_tcp_state(int);\nbool ec800m_is_ready(void);\nvoid ec800m_get_imei(char *,uint8_t);\nbool ec800m_ota_channel_prepare(void);\n",
            "debug_uart.h": "void dbg_printf(const char *, ...);\n",
            "hw_init.h": "void delay_ms(unsigned);\n",
            "n32l40x.h": "void NVIC_SystemReset(void);\nvoid IWDG_ReloadKey(void);\n",
        }.items():
            (t / name).write_text(body, encoding="utf-8")
        (t / "harness.c").write_text("""#include <assert.h>
#include <string.h>
#include "config.h"
#include "ec800m.h"
#include "ext_flash_layout.h"
#include "fota.h"
#include "ext_flash_store.h"
#include "bcr.h"
volatile uint32_t g_tick_ms;
static const config_t cfg = { 4096, "http://example.invalid/manifest", "0123456789abcdef" };
const config_t *cfg_get(void) { return &cfg; }
bool bcr_valid(const bcr_record_t *r) { (void)r; return false; }
bool firmware_signature_verify(const uint8_t*h,const uint8_t*s){(void)h;(void)s;return false;}
bool spi_flash_read(uint32_t a,uint8_t *b,uint32_t n){memset(b,0xff,n);return a+n<=FLASH_TOTAL_SIZE;}
bool spi_flash_write(uint32_t a,const uint8_t *b,uint32_t n){(void)b;return a+n<=FLASH_TOTAL_SIZE;}
spi_flash_program_result_t spi_flash_write_result(uint32_t a,const uint8_t*b,uint32_t n){(void)b;return a+n<=FLASH_TOTAL_SIZE?SPI_FLASH_PROGRAM_COMPLETED:SPI_FLASH_PROGRAM_NOT_ISSUED;}
bool spi_flash_erase_sector(uint32_t a){return a<FLASH_TOTAL_SIZE&&!(a%FLASH_SECTOR_SIZE);}
void spi_flash_note_verify_failure(void){}
int ec800m_tcp_open(int c,const char *h,uint16_t p){(void)c;(void)h;(void)p;return -1;}
int ec800m_tcp_send(int c,const uint8_t *p,uint16_t n){(void)c;(void)p;(void)n;return -1;}
void ec800m_tcp_close(int c){(void)c;}
bool ec800m_is_ready(void){return true;}
bool jt808_is_online(void){return true;}
void ec800m_get_imei(char *out,uint8_t n){if(n)out[0]=0;}
bool ec800m_ota_channel_prepare(void){return true;}
tcp_state_t ec800m_tcp_state(int c){(void)c;return TCP_STATE_CLOSED;}
void IWDG_ReloadKey(void){}
int terminal_identity_sync(char pid[12], char phone[13], char terminal[8]){(void)pid;(void)phone;(void)terminal;return 1;}
void dbg_printf(const char *f,...){(void)f;} void delay_ms(unsigned m){(void)m;} void NVIC_SystemReset(void){}
int main(void){assert(ext_flash_try_lock(EXT_FLASH_OWNER_CONFIG));assert(fota_start("http://example.invalid/fw.bin")<0);assert(!ext_flash_try_lock(EXT_FLASH_OWNER_OTA));ext_flash_unlock(EXT_FLASH_OWNER_CONFIG);assert(ext_flash_try_lock(EXT_FLASH_OWNER_OTA));ext_flash_unlock(EXT_FLASH_OWNER_OTA);return 0;}
""", encoding="utf-8")
        exe=t/"fota_lock_test.exe"
        subprocess.run([cc,"-std=c99","-I",str(t),"-I",str(ROOT/"include"),"-I",str(ROOT/"bootloader"/"include"),str(ROOT/"src"/"ext_flash_store.c"),str(ROOT/"src"/"service_workspace.c"),str(ROOT/"src"/"fota.c"),str(ROOT/"src"/"sha256.c"),str(ROOT/"src"/"fota_checkpoint.c"),str(ROOT/"src"/"fota_check_parser.c"),str(ROOT/"src"/"crc32.c"),str(t/"harness.c"),"-o",str(exe)],check=True,capture_output=True,text=True)
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
typedef enum { SPI_FLASH_PROGRAM_NOT_ISSUED=0, SPI_FLASH_PROGRAM_ISSUED_UNCERTAIN, SPI_FLASH_PROGRAM_COMPLETED } spi_flash_program_result_t;
bool spi_flash_read(uint32_t,uint8_t*,uint32_t);
bool spi_flash_write(uint32_t,const uint8_t*,uint32_t);
spi_flash_program_result_t spi_flash_write_result(uint32_t,const uint8_t*,uint32_t);
bool spi_flash_erase_sector(uint32_t);
void spi_flash_note_verify_failure(void);
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
typedef enum { EXT_FLASH_PROGRAM_NOT_ISSUED=0, EXT_FLASH_PROGRAM_ISSUED_UNCERTAIN, EXT_FLASH_PROGRAM_VERIFIED } ext_flash_program_result_t;
ext_flash_program_result_t ext_flash_write_result(ext_flash_owner_t,uint32_t,const void*,uint32_t);
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
static spi_flash_program_result_t program_result = SPI_FLASH_PROGRAM_COMPLETED;
static int verify_noted;
bool spi_flash_read(uint32_t a,uint8_t*b,uint32_t n){ memset(b,0x5a,n); return a+n<=FLASH_TOTAL_SIZE; }
bool spi_flash_write(uint32_t a,const uint8_t*b,uint32_t n){ (void)b; return !fail_write && a+n<=FLASH_TOTAL_SIZE; }
spi_flash_program_result_t spi_flash_write_result(uint32_t a,const uint8_t*b,uint32_t n){ (void)b; return a+n<=FLASH_TOTAL_SIZE?program_result:SPI_FLASH_PROGRAM_NOT_ISSUED; }
bool spi_flash_erase_sector(uint32_t a){ return a<FLASH_TOTAL_SIZE && !(a%FLASH_SECTOR_SIZE); }
void spi_flash_note_verify_failure(void){++verify_noted;}
int main(void){ uint8_t b[4],d[4]={1,2,3,4}; assert(ext_flash_try_lock(EXT_FLASH_OWNER_CONFIG)); tick_reads=0; assert(!ext_flash_try_lock(EXT_FLASH_OWNER_OTA)); assert(tick_reads>0); tick_reads=0; assert(!ext_flash_try_lock_now(EXT_FLASH_OWNER_BLIND_ZONE)); assert(tick_reads==0); assert(!ext_flash_read(EXT_FLASH_OWNER_OTA,0,b,1)); assert(ext_flash_read(EXT_FLASH_OWNER_CONFIG,0,b,1)); assert(!ext_flash_erase(EXT_FLASH_OWNER_CONFIG,1,FLASH_SECTOR_SIZE)); assert(ext_flash_erase(EXT_FLASH_OWNER_CONFIG,0,FLASH_SECTOR_SIZE)); fail_write=1; assert(!ext_flash_write_verified(EXT_FLASH_OWNER_CONFIG,0,d,sizeof d)); assert(verify_noted==0); program_result=SPI_FLASH_PROGRAM_NOT_ISSUED; assert(ext_flash_write_result(EXT_FLASH_OWNER_CONFIG,0,d,sizeof d)==EXT_FLASH_PROGRAM_NOT_ISSUED); program_result=SPI_FLASH_PROGRAM_ISSUED_UNCERTAIN; assert(ext_flash_write_result(EXT_FLASH_OWNER_CONFIG,0,d,sizeof d)==EXT_FLASH_PROGRAM_ISSUED_UNCERTAIN); program_result=SPI_FLASH_PROGRAM_COMPLETED; assert(ext_flash_write_result(EXT_FLASH_OWNER_CONFIG,0,d,sizeof d)==EXT_FLASH_PROGRAM_ISSUED_UNCERTAIN); assert(verify_noted==1); ext_flash_unlock(EXT_FLASH_OWNER_CONFIG); assert(ext_flash_try_lock(EXT_FLASH_OWNER_OTA)); ext_flash_unlock(EXT_FLASH_OWNER_OTA); return 0;}
""", encoding="utf-8")
        exe = t / "host_test.exe"
        cmd = [cc, "-std=c99", "-I", str(t), str(ROOT / "src" / "ext_flash_store.c"), str(t / "harness.c"), "-o", str(exe)]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        subprocess.run([str(exe)], check=True, capture_output=True, text=True)

def test_spi_flash_page_program_issue_boundary():
    cc = _compiler()
    if not cc:
        return
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "config.h").write_text("""#include <stdint.h>
extern volatile uint32_t g_tick_ms;
#define TICK_MS() g_tick_ms
""", encoding="utf-8")
        (t / "hw_init.h").write_text("""#include <stdint.h>
extern void *test_spi;
#define FLASH_SPI test_spi
void test_cs_low(void); void test_cs_high(void);
void delay_ms(uint32_t ms);
#define FLASH_CS_LOW() test_cs_low()
#define FLASH_CS_HIGH() test_cs_high()
""", encoding="utf-8")
        (t / "debug_uart.h").write_text(
            "void dbg_printf(const char *format, ...);\n", encoding="utf-8")
        (t / "n32l40x.h").write_text("""#include <stdint.h>
#define RESET 0
#define SET 1
#define SPI_I2S_TE_FLAG 1U
#define SPI_I2S_RNE_FLAG 2U
int SPI_I2S_GetStatus(void *, uint32_t);
void SPI_I2S_TransmitData(void *, uint16_t);
uint16_t SPI_I2S_ReceiveData(void *);
""", encoding="utf-8")
        (t / "harness.c").write_text("""#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include "spi_flash.h"
#include "n32l40x.h"
volatile uint32_t g_tick_ms;
void *test_spi;
static unsigned delay_total;
static uint8_t command, tx_index;
static bool program_next;
static unsigned fault_mode;
void test_cs_low(void) { command = 0U; tx_index = 0U; }
void test_cs_high(void) {
    if (command == 0x05U) program_next = true;
}
void delay_ms(uint32_t ms) { delay_total += ms; g_tick_ms += ms; }
void dbg_printf(const char *format, ...) { (void)format; }
int SPI_I2S_GetStatus(void *spi, uint32_t flag) {
    (void)spi;
    if (program_next && tx_index == 0U && flag == SPI_I2S_TE_FLAG && fault_mode == 1U)
        return RESET;
    if (program_next && tx_index == 1U && flag == SPI_I2S_RNE_FLAG && fault_mode == 2U)
        return RESET;
    return SET;
}
void SPI_I2S_TransmitData(void *spi, uint16_t value) {
    (void)spi;
    if (tx_index++ == 0U) command = (uint8_t)value;
}
uint16_t SPI_I2S_ReceiveData(void *spi) {
    (void)spi;
    if (command == 0x9fU) {
        static const uint8_t id[] = {0U, 0x68U, 0x40U, 0x15U};
        return id[tx_index - 1U];
    }
    if (command == 0x05U) return tx_index == 2U ? 0x02U : 0U;
    return 0U;
}
static void arm(unsigned mode) { fault_mode = 0U; program_next = false; fault_mode = mode; }
int main(void) {
    uint8_t value = 0x54U;
    spi_flash_diagnostics_t diag;
    spi_flash_init();
    spi_flash_get_diagnostics(&diag);
    assert(delay_total >= 1U);
    assert(diag.jedec_id == 0x684015UL);
    assert(diag.failure == SPI_FLASH_FAILURE_NONE);
    assert(spi_flash_read_id() == 0x6840U);
    arm(1U);
    assert(spi_flash_write_result(0U, &value, 1U) == SPI_FLASH_PROGRAM_NOT_ISSUED);
    arm(2U);
    assert(spi_flash_write_result(0U, &value, 1U) == SPI_FLASH_PROGRAM_ISSUED_UNCERTAIN);
    spi_flash_get_diagnostics(&diag);
    assert(diag.failure == SPI_FLASH_FAILURE_PROGRAM);
    spi_flash_note_verify_failure();
    assert(strcmp(spi_flash_failure_name(SPI_FLASH_FAILURE_VERIFY), "VERIFY") == 0);
    spi_flash_get_diagnostics(&diag);
    assert(diag.failure == SPI_FLASH_FAILURE_VERIFY);
    return 0;
}
""", encoding="utf-8")
        exe = t / "spi_issue_test.exe"
        built = subprocess.run(
            [cc, "-std=c99", "-Wall", "-Wextra", "-Werror",
             "-I", str(t), "-I", str(ROOT / "include"),
             str(ROOT / "src" / "spi_flash.c"), str(t / "harness.c"),
             "-o", str(exe)], capture_output=True, text=True)
        if built.returncode != 0:
            raise RuntimeError(built.stderr or built.stdout)
        subprocess.run([str(exe)], check=True, capture_output=True, text=True)

if __name__ == "__main__":
    test_fota_failed_lock_does_not_unlock_owner()
    test_owner_bounds_alignment_and_error_propagation()
    test_spi_flash_page_program_issue_boundary()
    print("test_ext_flash_store_host: PASS")
