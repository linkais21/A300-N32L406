import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).parents[2]


def _compiler():
    return shutil.which("gcc") or shutil.which("clang") or shutil.which("cc")


def test_fota_failed_lock_does_not_unlock_owner():
    """Run the actual fota_start lock-failure path against the real arbiter."""
    cc = _compiler()
    if not cc:
        return
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "fota.h").write_text(
            """#include <stdint.h>\n#include <stdbool.h>\n#define FOTA_FLASH_ADDR 0x10000U\n#define FOTA_MAX_SIZE 0x1000U\n#define FOTA_PENDING_ADDR 0x20000U\n#define FOTA_PENDING_MAGIC 0xF07AF07AU\ntypedef enum { FOTA_STATE_IDLE=0, FOTA_STATE_CONNECTING, FOTA_STATE_DOWNLOADING, FOTA_STATE_VERIFYING, FOTA_STATE_READY, FOTA_STATE_ERROR } fota_state_t;\nvoid fota_init(void); int fota_start(const char *);\n""",
            encoding="utf-8",
        )
        (t / "ext_flash_layout.h").write_text(
            """#include <stdint.h>\n#define FLASH_TOTAL_SIZE (2U*1024U*1024U)\n#define FLASH_SECTOR_SIZE 4096U\n""",
            encoding="utf-8",
        )
        (t / "spi_flash.h").write_text(
            """#include <stdint.h>\n#include <stdbool.h>\n#define FLASH_SECTOR_SIZE 4096U\nbool spi_flash_read(uint32_t, uint8_t *, uint32_t);\nbool spi_flash_write(uint32_t, const uint8_t *, uint32_t);\nbool spi_flash_erase_sector(uint32_t);\n""",
            encoding="utf-8",
        )
        (t / "ext_flash_store.h").write_text(
            """#include <stdint.h>\n#include <stdbool.h>\ntypedef enum { EXT_FLASH_OWNER_NONE=0, EXT_FLASH_OWNER_OTA, EXT_FLASH_OWNER_AGNSS, EXT_FLASH_OWNER_BLIND_ZONE, EXT_FLASH_OWNER_CONFIG } ext_flash_owner_t;\nbool ext_flash_try_lock(ext_flash_owner_t);\nvoid ext_flash_unlock(ext_flash_owner_t);\nbool ext_flash_read(ext_flash_owner_t, uint32_t, void *, uint32_t);\nbool ext_flash_write_verified(ext_flash_owner_t, uint32_t, const void *, uint32_t);\nbool ext_flash_erase(ext_flash_owner_t, uint32_t, uint32_t);\n""",
            encoding="utf-8",
        )
        (t / "config.h").write_text(
            """#include <stdint.h>\nextern volatile uint32_t g_tick_ms;\n#define TICK_MS() g_tick_ms\n#define SPI_FLASH_TIMEOUT_MS 2U\n#define CFG_IP_LEN 64\ntypedef struct { uint32_t fota_size; } config_t;\nconst config_t *cfg_get(void);\n""",
            encoding="utf-8",
        )
        for name, body in {
            "ec800m.h": "#include <stdint.h>\n#define EC800M_CH_OTA 1\nint ec800m_tcp_open(int, const char *, uint16_t);\nvoid ec800m_tcp_send(int, const uint8_t *, uint16_t);\n",
            "debug_uart.h": "void dbg_printf(const char *, ...);\n",
            "hw_init.h": "void delay_ms(unsigned);\n",
            "n32l40x.h": "void NVIC_SystemReset(void);\n",
        }.items():
            (t / name).write_text(body, encoding="utf-8")
        (t / "harness.c").write_text(
            """#include <assert.h>\n#include <stdint.h>\n#include <string.h>\n#include \"fota.h\"\n#include \"ext_flash_store.h\"\nvolatile uint32_t g_tick_ms;\nstatic const config_t cfg = { 0 };\nconst config_t *cfg_get(void) { return &cfg; }\nbool spi_flash_read(uint32_t a, uint8_t *b, uint32_t n) { memset(b, 0xff, n); return a+n <= FLASH_TOTAL_SIZE; }\nbool spi_flash_write(uint32_t a, const uint8_t *b, uint32_t n) { (void)b; return a+n <= FLASH_TOTAL_SIZE; }\nbool spi_flash_erase_sector(uint32_t a) { return a < FLASH_TOTAL_SIZE && !(a % FLASH_SECTOR_SIZE); }\nint ec800m_tcp_open(int ch, const char *host, uint16_t port) { (void)ch; (void)host; (void)port; return -1; }\nvoid ec800m_tcp_send(int ch, const uint8_t *p, uint16_t n) { (void)ch; (void)p; (void)n; }\nvoid dbg_printf(const char *fmt, ...) { (void)fmt; }\nvoid delay_ms(unsigned ms) { (void)ms; }\nvoid NVIC_SystemReset(void) {}\nint main(void) {\n    assert(ext_flash_try_lock(EXT_FLASH_OWNER_CONFIG));\n    assert(fota_start(\"http://example.invalid/fw.bin\") < 0);\n    /* A failed OTA acquisition must not release CONFIG's lock. */\n    assert(!ext_flash_try_lock(EXT_FLASH_OWNER_OTA));\n    ext_flash_unlock(EXT_FLASH_OWNER_CONFIG);\n    assert(ext_flash_try_lock(EXT_FLASH_OWNER_OTA));\n    ext_flash_unlock(EXT_FLASH_OWNER_OTA);\n    return 0;\n}\n""",
            encoding="utf-8",
        )
        exe = t / "fota_lock_test.exe"
        cmd = [
            cc,
            "-std=c99",
            "-I",
            str(t),
            str(ROOT / "src" / "ext_flash_store.c"),
            str(ROOT / "src" / "fota.c"),
            str(t / "harness.c"),
            "-o",
            str(exe),
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        subprocess.run([str(exe)], check=True, capture_output=True, text=True)


def test_owner_bounds_alignment_and_error_propagation():
    cc = _compiler()
    if not cc:
        return
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "spi_flash.h").write_text("""#ifndef SPI_FLASH_H\n#define SPI_FLASH_H\n#include <stdint.h>\n#include <stdbool.h>\n#define FLASH_PAGE_SIZE 256\n#define FLASH_SECTOR_SIZE 4096\n#define FLASH_TOTAL_SIZE (2*1024*1024)\nbool spi_flash_read(uint32_t,uint8_t*,uint32_t);\nbool spi_flash_write(uint32_t,const uint8_t*,uint32_t);\nbool spi_flash_erase_sector(uint32_t);\n#endif\n""", encoding="utf-8")
        (t / "config.h").write_text("#include <stdint.h>\nextern volatile uint32_t g_tick_ms;\n#define TICK_MS() g_tick_ms\n#define SPI_FLASH_TIMEOUT_MS 2U\n", encoding="utf-8")
        (t / "ext_flash_layout.h").write_text("""#include <stdint.h>\n#include \"spi_flash.h\"\ntypedef enum { EXT_FLASH_OWNER_NONE=0, EXT_FLASH_OWNER_OTA, EXT_FLASH_OWNER_AGNSS, EXT_FLASH_OWNER_BLIND_ZONE, EXT_FLASH_OWNER_CONFIG } ext_flash_owner_t;\n""", encoding="utf-8")
        (t / "ext_flash_store.h").write_text("""#include <stdint.h>\n#include <stdbool.h>\n#include \"ext_flash_layout.h\"\nbool ext_flash_read(ext_flash_owner_t,uint32_t,void*,uint32_t);\nbool ext_flash_write_verified(ext_flash_owner_t,uint32_t,const void*,uint32_t);\nbool ext_flash_erase(ext_flash_owner_t,uint32_t,uint32_t);\nbool ext_flash_try_lock(ext_flash_owner_t);\nvoid ext_flash_unlock(ext_flash_owner_t);\n""", encoding="utf-8")
        (t / "harness.c").write_text("""#include <assert.h>\n#include <stdint.h>\n#include <string.h>\n#include \"ext_flash_store.h\"\nvolatile uint32_t g_tick_ms; static int fail_write;\nbool spi_flash_read(uint32_t a,uint8_t*b,uint32_t n){ memset(b,0x5a,n); return a+n<=FLASH_TOTAL_SIZE; }\nbool spi_flash_write(uint32_t a,const uint8_t*b,uint32_t n){ (void)b; return !fail_write && a+n<=FLASH_TOTAL_SIZE; }\nbool spi_flash_erase_sector(uint32_t a){ return a<FLASH_TOTAL_SIZE && !(a%FLASH_SECTOR_SIZE); }\nint main(void){ uint8_t b[4],d[4]={1,2,3,4}; assert(ext_flash_try_lock(EXT_FLASH_OWNER_CONFIG)); assert(!ext_flash_try_lock(EXT_FLASH_OWNER_OTA)); assert(!ext_flash_read(EXT_FLASH_OWNER_OTA,0,b,1)); assert(ext_flash_read(EXT_FLASH_OWNER_CONFIG,0,b,1)); assert(!ext_flash_erase(EXT_FLASH_OWNER_CONFIG,1,FLASH_SECTOR_SIZE)); assert(ext_flash_erase(EXT_FLASH_OWNER_CONFIG,0,FLASH_SECTOR_SIZE)); fail_write=1; assert(!ext_flash_write_verified(EXT_FLASH_OWNER_CONFIG,0,d,sizeof d)); ext_flash_unlock(EXT_FLASH_OWNER_CONFIG); assert(ext_flash_try_lock(EXT_FLASH_OWNER_OTA)); ext_flash_unlock(EXT_FLASH_OWNER_OTA); return 0;}\n""", encoding="utf-8")
        exe = t / "host_test.exe"
        cmd = [cc, "-std=c99", "-I", str(t), str(ROOT / "src" / "ext_flash_store.c"), str(t / "harness.c"), "-o", str(exe)]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        subprocess.run([str(exe)], check=True, capture_output=True, text=True)


if __name__ == "__main__":
    test_fota_failed_lock_does_not_unlock_owner()
    test_owner_bounds_alignment_and_error_propagation()
    print("test_ext_flash_store_host: PASS")
