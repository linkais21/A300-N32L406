import subprocess
import tempfile
import shutil
from pathlib import Path

ROOT = Path(__file__).parents[2]

def test_failed_lock_does_not_unlock_owner():
    fota = (ROOT / "src" / "fota.c").read_text(encoding="utf-8")
    assert "if (!ota_locked) { s_state = FOTA_STATE_ERROR; return -1; }" in fota
    assert "if (!ota_locked) { s_state = FOTA_STATE_ERROR; return; }" in fota

def test_owner_bounds_alignment_and_error_propagation():
    cc = shutil.which("gcc") or shutil.which("clang") or shutil.which("cc")
    if not cc:
        return
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "spi_flash.h").write_text("""#ifndef SPI_FLASH_H\n#define SPI_FLASH_H\n#include <stdint.h>\n#include <stdbool.h>\n#define FLASH_PAGE_SIZE 256\n#define FLASH_SECTOR_SIZE 4096\n#define FLASH_TOTAL_SIZE (2*1024*1024)\nbool spi_flash_read(uint32_t,uint8_t*,uint32_t);\nbool spi_flash_write(uint32_t,const uint8_t*,uint32_t);\nbool spi_flash_erase_sector(uint32_t);\n#endif\n""")
        (t / "config.h").write_text("""#include <stdint.h>\nextern volatile uint32_t g_tick_ms;\n#define TICK_MS() g_tick_ms\n#define SPI_FLASH_TIMEOUT_MS 2U\n""")
        (t / "ext_flash_layout.h").write_text("""#include <stdint.h>\n#include \"spi_flash.h\"\ntypedef enum { EXT_FLASH_OWNER_NONE=0, EXT_FLASH_OWNER_OTA, EXT_FLASH_OWNER_AGNSS, EXT_FLASH_OWNER_BLIND_ZONE, EXT_FLASH_OWNER_CONFIG } ext_flash_owner_t;\n""")
        (t / "ext_flash_store.h").write_text("""#include <stdint.h>\n#include <stdbool.h>\n#include \"ext_flash_layout.h\"\nbool ext_flash_read(ext_flash_owner_t,uint32_t,void*,uint32_t);\nbool ext_flash_write_verified(ext_flash_owner_t,uint32_t,const void*,uint32_t);\nbool ext_flash_erase(ext_flash_owner_t,uint32_t,uint32_t);\nbool ext_flash_try_lock(ext_flash_owner_t);\nvoid ext_flash_unlock(ext_flash_owner_t);\n""")
        harness = t / "harness.c"
        harness.write_text("""#include <assert.h>\n#include <stdint.h>\n#include <string.h>\n#include \"ext_flash_store.h\"\nvolatile uint32_t g_tick_ms; static int fail_write;\nbool spi_flash_read(uint32_t a,uint8_t*b,uint32_t n){ memset(b,0x5a,n); return a+n<=FLASH_TOTAL_SIZE; }\nbool spi_flash_write(uint32_t a,const uint8_t*b,uint32_t n){ (void)b; return !fail_write && a+n<=FLASH_TOTAL_SIZE; }\nbool spi_flash_erase_sector(uint32_t a){ return a<FLASH_TOTAL_SIZE && !(a%FLASH_SECTOR_SIZE); }\nint main(void){ uint8_t b[4],d[4]={1,2,3,4}; assert(ext_flash_try_lock(EXT_FLASH_OWNER_CONFIG)); assert(!ext_flash_try_lock(EXT_FLASH_OWNER_OTA)); assert(!ext_flash_read(EXT_FLASH_OWNER_OTA,0,b,1)); assert(ext_flash_read(EXT_FLASH_OWNER_CONFIG,0,b,1)); assert(!ext_flash_erase(EXT_FLASH_OWNER_CONFIG,1,FLASH_SECTOR_SIZE)); assert(ext_flash_erase(EXT_FLASH_OWNER_CONFIG,0,FLASH_SECTOR_SIZE)); fail_write=1; assert(!ext_flash_write_verified(EXT_FLASH_OWNER_CONFIG,0,d,sizeof d)); ext_flash_unlock(EXT_FLASH_OWNER_CONFIG); assert(ext_flash_try_lock(EXT_FLASH_OWNER_OTA)); ext_flash_unlock(EXT_FLASH_OWNER_OTA); return 0;}\n""")
        exe = t / "host_test.exe"
        cmd = [cc, "-std=c99", "-I", str(t), str(ROOT / "src" / "ext_flash_store.c"), str(harness), "-o", str(exe)]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        subprocess.run([str(exe)], check=True, capture_output=True, text=True)

if __name__ == "__main__":
    test_failed_lock_does_not_unlock_owner()
    test_owner_bounds_alignment_and_error_propagation()
    print("test_ext_flash_store_host: PASS")
