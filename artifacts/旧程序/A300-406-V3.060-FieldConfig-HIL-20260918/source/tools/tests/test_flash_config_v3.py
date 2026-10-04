#!/usr/bin/env python3
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]

HARNESS = r'''
#include <assert.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "flash_config.h"
#include "ext_flash_store.h"
#include "spi_flash.h"

#define FLASH_BYTES (2U * FLASH_SECTOR_SIZE)
#define MAIN_CH 0U
#define BACKUP_CH 3U

static uint8_t flash_image[FLASH_BYTES];
static int locked;
static int operation_count;
static int fail_operation;
static char debug_log[2048];
static size_t debug_used;
static spi_flash_failure_t flash_failure = SPI_FLASH_FAILURE_ERASE;

static uint8_t *flash_at(uint32_t addr, uint32_t len)
{
    assert(addr + len <= FLASH_BYTES);
    return &flash_image[addr];
}

static int operation_fails(void)
{
    ++operation_count;
    return fail_operation == operation_count;
}

static void nor_program(uint32_t addr, const void *data, uint32_t len)
{
    const uint8_t *input = (const uint8_t *)data;
    uint8_t *output = flash_at(addr, len);
    uint32_t i;
    for (i = 0U; i < len; ++i)
        output[i] &= input[i];
}

bool ext_flash_try_lock(ext_flash_owner_t owner)
{
    assert(owner == EXT_FLASH_OWNER_CONFIG);
    if (locked)
        return false;
    locked = 1;
    return true;
}

void ext_flash_unlock(ext_flash_owner_t owner)
{
    assert(owner == EXT_FLASH_OWNER_CONFIG && locked);
    locked = 0;
}

bool ext_flash_read(ext_flash_owner_t owner, uint32_t addr, void *data,
                    uint32_t len)
{
    assert(owner == EXT_FLASH_OWNER_CONFIG && locked);
    memcpy(data, flash_at(addr, len), len);
    return true;
}

bool ext_flash_erase(ext_flash_owner_t owner, uint32_t addr, uint32_t len)
{
    assert(owner == EXT_FLASH_OWNER_CONFIG && locked);
    assert((addr == CFG_FLASH_ADDR_A || addr == CFG_FLASH_ADDR_B) &&
           len == FLASH_SECTOR_SIZE);
    if (operation_fails())
        return false;
    memset(flash_at(addr, len), 0xFF, len);
    return true;
}

bool ext_flash_write_verified(ext_flash_owner_t owner, uint32_t addr,
                              const void *data, uint32_t len)
{
    assert(owner == EXT_FLASH_OWNER_CONFIG && locked);
    if (operation_fails()) {
        nor_program(addr, data, len / 2U);
        return false;
    }
    nor_program(addr, data, len);
    return memcmp(flash_at(addr, len), data, len) == 0;
}

ext_flash_program_result_t ext_flash_write_result(
    ext_flash_owner_t owner, uint32_t addr, const void *data, uint32_t len)
{
    assert(owner == EXT_FLASH_OWNER_CONFIG && locked);
    if (operation_fails())
        return EXT_FLASH_PROGRAM_NOT_ISSUED;
    nor_program(addr, data, len);
    return EXT_FLASH_PROGRAM_VERIFIED;
}

void dbg_printf(const char *fmt, ...)
{
    va_list args;
    int written;
    if (debug_used >= sizeof(debug_log))
        return;
    va_start(args, fmt);
    written = vsnprintf(debug_log + debug_used, sizeof(debug_log) - debug_used,
                        fmt, args);
    va_end(args);
    if (written > 0) {
        size_t count = (size_t)written;
        debug_used += count < sizeof(debug_log) - debug_used ? count :
                      sizeof(debug_log) - debug_used - 1U;
    }
}

void spi_flash_get_diagnostics(spi_flash_diagnostics_t *out)
{
    memset(out, 0, sizeof(*out));
    out->failure = flash_failure;
}

const char *spi_flash_failure_name(spi_flash_failure_t failure)
{
    return failure == SPI_FLASH_FAILURE_ERASE ? "ERASE" : "NONE";
}

static void set_text(char *output, size_t capacity, const char *input)
{
    size_t length = strlen(input);
    assert(length < capacity);
    memset(output, 0, capacity);
    memcpy(output, input, length);
}

static device_config_t candidate(const char *server, const char *main_auth,
                                 const char *backup_auth)
{
    device_config_t cfg = k_config_defaults;
    set_text(cfg.server_ip, sizeof(cfg.server_ip), server);
    set_text(cfg.auth_code, sizeof(cfg.auth_code), main_auth);
    set_text(cfg.backup_auth_code, sizeof(cfg.backup_auth_code), backup_auth);
    return cfg;
}

static void restart_without_fault(void)
{
    locked = 0;
    fail_operation = -1;
    operation_count = 0;
    cfg_init();
}

static void test_independent_auth_codes(void)
{
    memset(flash_image, 0xFF, sizeof(flash_image));
    locked = 0;
    fail_operation = -1;
    operation_count = 0;
    debug_used = 0U;
    debug_log[0] = '\0';
    cfg_init();
    assert(strstr(debug_log, "[CFG] defaults persisted slot=A gen=2") != NULL);

    assert(cfg_set_auth_code(MAIN_CH, "MAIN-AUTH"));
    assert(strcmp(cfg_get()->auth_code, "MAIN-AUTH") == 0);
    assert(cfg_get()->backup_auth_code[0] == '\0');
    assert(cfg_set_auth_code(BACKUP_CH, "BACK-AUTH"));
    assert(strcmp(cfg_get()->auth_code, "MAIN-AUTH") == 0);
    assert(strcmp(cfg_get()->backup_auth_code, "BACK-AUTH") == 0);
    assert(!cfg_set_auth_code(1U, "WRONG-CHANNEL"));
    assert(!cfg_set_auth_code(MAIN_CH,
        "AUTH-CODE-THAT-IS-DELIBERATELY-LONGER-THAN-THE-FIELD"));

    restart_without_fault();
    assert(strcmp(cfg_get()->auth_code, "MAIN-AUTH") == 0);
    assert(strcmp(cfg_get()->backup_auth_code, "BACK-AUTH") == 0);
}

static void test_default_persistence_failure_is_logged(void)
{
    memset(flash_image, 0xFF, sizeof(flash_image));
    locked = 0;
    fail_operation = 1;
    operation_count = 0;
    debug_used = 0U;
    debug_log[0] = '\0';
    cfg_init();
    assert(strstr(debug_log,
                  "[CFG] persist failed slot=B gen=1 result=3 stage=ERASE") != NULL);
}

static void test_power_cut_never_loads_mixed_candidate(void)
{
    uint8_t baseline[sizeof(flash_image)];
    device_config_t old_cfg = candidate("old-server", "OLD-MAIN", "OLD-BACK");
    device_config_t new_cfg = candidate("new-server", "NEW-MAIN", "NEW-BACK");
    new_cfg.province_be[1] = 44U;
    new_cfg.city_be[0] = 1U; new_cfg.city_be[1] = 44U;
    new_cfg.plate_color = 2U; new_cfg.plate_color_valid = 1U;
    new_cfg.mileage_m = 1234500U;
    set_text(new_cfg.plate_no, sizeof new_cfg.plate_no, "A12345");
    int successful_operations;
    int cut;

    memset(flash_image, 0xFF, sizeof(flash_image));
    locked = 0;
    fail_operation = -1;
    operation_count = 0;
    cfg_init();
    assert(cfg_store_candidate(&old_cfg));
    memcpy(baseline, flash_image, sizeof(baseline));

    operation_count = 0;
    assert(cfg_store_candidate(&new_cfg));
    successful_operations = operation_count;
    assert(successful_operations >= 3);

    for (cut = 1; cut <= successful_operations; ++cut) {
        int is_old;
        int is_new;
        memcpy(flash_image, baseline, sizeof(flash_image));
        restart_without_fault();
        operation_count = 0;
        fail_operation = cut;
        (void)cfg_store_candidate(&new_cfg);
        restart_without_fault();

        is_old = strcmp(cfg_get()->server_ip, "old-server") == 0 &&
                 strcmp(cfg_get()->auth_code, "OLD-MAIN") == 0 &&
                 strcmp(cfg_get()->backup_auth_code, "OLD-BACK") == 0;
        is_new = strcmp(cfg_get()->server_ip, "new-server") == 0 &&
                 strcmp(cfg_get()->auth_code, "NEW-MAIN") == 0 &&
                 strcmp(cfg_get()->backup_auth_code, "NEW-BACK") == 0;
        assert(is_old || is_new);
        assert(memcmp(cfg_get(), is_old ? &old_cfg : &new_cfg,
                      sizeof(device_config_t)) == 0);
    }
}

static void test_mileage_updates_are_deferred(void)
{
    uint32_t initial;
    int before;
    memset(flash_image, 0xFF, sizeof(flash_image));
    locked = 0;
    fail_operation = -1;
    operation_count = 0;
    debug_used = 0U;
    cfg_init();
    initial = cfg_get()->mileage_m;
    operation_count = 0;
    for (unsigned i = 0U; i < 500U; ++i)
        cfg_add_mileage(1U);
    assert(cfg_get()->mileage_m == initial + 500U);
    assert(cfg_mileage_dirty());
    assert(operation_count == 0);
    before = operation_count;
    assert(cfg_flush_mileage());
    assert(!cfg_mileage_dirty());
    assert(operation_count > before);

    cfg_add_mileage(7U);
    operation_count = 0;
    fail_operation = 1;
    assert(!cfg_flush_mileage());
    assert(cfg_mileage_dirty());
    fail_operation = -1;
    operation_count = 0;
    assert(cfg_flush_mileage());
    assert(!cfg_mileage_dirty());

    cfg_add_mileage(9U);
    assert(cfg_mileage_dirty());
    cfg_set_heartbeat((uint16_t)(cfg_get()->heartbeat_s + 1U));
    assert(!cfg_mileage_dirty());
}

int main(void)
{
    assert(CFG_VERSION == 4U);
    assert(CFG_COMMIT_MARKER == 0x43464733UL);
    assert(k_config_defaults.device_api_key[0] == '\0');
    assert(sizeof(device_config_t) + 20U < FLASH_SECTOR_SIZE);
    assert(cfg_store_candidate_result(NULL) == CFG_STORE_INVALID);
    test_default_persistence_failure_is_logged();
    test_independent_auth_codes();
    test_power_cut_never_loads_mixed_candidate();
    test_mileage_updates_are_deferred();
    return 0;
}
'''


def find_compiler():
    compiler = os.environ.get("CC") or shutil.which("gcc") or shutil.which("clang") or shutil.which("cc")
    if compiler:
        return compiler
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if "WinLibs" in directory and directory.rstrip("\\/").lower().endswith("bin"):
            return str(Path(directory.strip('"')) / "gcc.exe")
    return None


def main() -> int:
    compiler = find_compiler()
    if compiler is None:
        print("test_flash_config_v3: FAIL (host C compiler required)")
        return 1
    with tempfile.TemporaryDirectory(prefix="flash_config_v3_") as directory:
        temp = Path(directory)
        harness = temp / "harness.c"
        executable = temp / "flash_config_v3.exe"
        harness.write_text(HARNESS, encoding="utf-8")
        command = [compiler, "-std=c99", "-Wall", "-Wextra", "-Werror",
                   "-I", str(ROOT / "include"), str(harness),
                   str(ROOT / "src" / "flash_config.c"), str(ROOT / "src" / "crc32.c"),
                   "-o", str(executable)]
        build = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        if build.returncode != 0:
            print(build.stdout + build.stderr, end="")
            print("test_flash_config_v3: FAIL (C harness did not compile)")
            return build.returncode
        run = subprocess.run([str(executable)], cwd=ROOT, capture_output=True, text=True)
        if run.returncode != 0:
            print(run.stdout + run.stderr, end="")
            print("test_flash_config_v3: FAIL (C harness assertion)")
            return run.returncode
    print("test_flash_config_v3: C99 NOR power-cut coverage PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
