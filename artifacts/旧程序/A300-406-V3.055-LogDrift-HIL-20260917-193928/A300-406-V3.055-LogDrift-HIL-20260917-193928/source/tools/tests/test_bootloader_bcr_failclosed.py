"""Run BCR/boot selection with failed external Flash reads."""

from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]

HARNESS = r'''
#include <assert.h>
#include <setjmp.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "bcr.h"
#include "image_install.h"
#include "image_verify.h"
#include "bootloader_config.h"
#include "factory_init.h"

int bootloader_main(void);
static uint8_t slots[2][4096];
static unsigned read_fail, reads[2], jumps, writes, erases, feeds, recovery;
static bool fault_reset, fail_once;
static jmp_buf done;

bool boot_bcr_read(uint32_t address, void *data, uint32_t length)
{
    unsigned slot = address == BCR_SLOT_B_ADDR;
    assert(address == BCR_SLOT_A_ADDR || address == BCR_SLOT_B_ADDR);
    assert(length == sizeof(bcr_record_t));
    ++reads[slot];
    if (read_fail & (1U << slot)) {
        if (fail_once) read_fail &= ~(1U << slot);
        return false;
    }
    memcpy(data, slots[slot], length);
    return true;
}
bool boot_bcr_erase(uint32_t address) { (void)address; ++erases; return false; }
bool boot_bcr_write(uint32_t address, const void *data, uint32_t length)
{ (void)address; (void)data; (void)length; ++writes; return false; }
bool boot_bcr_readback(uint32_t address, const void *data, uint32_t length)
{ (void)address; (void)data; (void)length; return false; }
bool boot_ext_read(uint32_t address, void *data, uint32_t length)
{ (void)address; (void)data; (void)length; return false; }
bool boot_ext_write(uint32_t address, const void *data, uint32_t length)
{ (void)address; (void)data; (void)length; ++writes; return false; }
bool boot_ext_erase(uint32_t address, uint32_t length)
{ (void)address; (void)length; ++erases; return false; }
bool boot_ext_is_complete(uint32_t address, uint32_t length)
{ (void)address; (void)length; return false; }
bool boot_int_flash_read(uint32_t address, void *data, uint32_t length)
{ (void)address; (void)data; (void)length; return false; }
bool boot_int_flash_program(uint32_t address, const void *data, uint32_t length)
{ (void)address; (void)data; (void)length; ++writes; return false; }
bool boot_int_flash_erase(uint32_t address, uint32_t length)
{ (void)address; (void)length; ++erases; return false; }
bool firmware_signature_verify(const uint8_t *digest, const uint8_t *signature)
{ (void)digest; (void)signature; return false; }
bool boot_platform_init(void) { return true; }
const factory_init_request_t *factory_init_request(void)
{
    static const factory_init_request_t request = {0};
    return &request;
}
factory_init_result_t factory_init_apply(const factory_init_request_t *request)
{ (void)request; return FACTORY_INIT_RESULT_ALREADY_DONE; }
bool boot_reset_was_fault_or_watchdog(void) { return fault_reset; }
void boot_jump_to(uint32_t address) { assert(address == APP_FLASH_BASE); ++jumps; }
bool boot_app_vectors_valid(uint32_t address) { (void)address; return true; }
void boot_install_progress(uint32_t done, uint32_t total, bool complete) {(void)done;(void)total;(void)complete;}
void boot_watchdog_feed(void) { ++feeds; }
void boot_recovery_step(void) { if (++recovery == 4U) longjmp(done, 1); }

static void seed(unsigned slot, uint32_t sequence, uint8_t state)
{
    bcr_record_t record = {0};
    record.magic = BCR_MAGIC;
    record.sequence = sequence;
    record.state = state;
    record.image_version = 3002;
    record.transaction_offset = 2048;
    record.transaction_length = 4097;
    record.target_address = APP_FLASH_BASE;
    record.commit_marker = BCR_COMMIT_MARKER;
    record.crc32 = image_crc32(&record, offsetof(bcr_record_t, crc32));
    memcpy(slots[slot], &record, sizeof record);
}

int main(int argc, char **argv)
{
    assert(argc == 3);
    unsigned scenario = (unsigned)strtoul(argv[1], NULL, 10);
    fault_reset = strtoul(argv[2], NULL, 10) != 0;
    memset(slots, 0xff, sizeof slots);
    switch (scenario) {
    case 0: seed(0, 8, BCR_ACTIVE); seed(1, 9, BCR_PENDING); read_fail=2; break;
    case 1: seed(0, 8, BCR_ACTIVE); seed(1, 9, BCR_PENDING); read_fail=3; break;
    case 2: break; /* Both records are confirmed erased, not an I/O failure. */
    case 3: memset(slots, 0, sizeof slots); break;
    case 4: seed(0, 8, 0x7f); break;
    case 5: seed(0, 8, BCR_RECOVERY); break;
    case 6: seed(0, 8, BCR_ACTIVE); break;
    case 7: seed(0, 8, BCR_TRIAL); seed(1, 9, BCR_PENDING); read_fail=2; break;
    case 8: seed(0, 9, BCR_PENDING); seed(1, 8, BCR_ACTIVE); read_fail=1; break;
    case 9: seed(0, 8, BCR_TRIAL); seed(1, 9, BCR_PENDING); read_fail=2; fail_once=true; break;
    default: assert(0);
    }
    if (scenario == 9) {
        /* After a transient failure, only a fresh read of BOTH slots may
         * expose the newer Pending; never account the stale Trial instead. */
        bcr_record_t record;
        assert(bcr_load(&record) == BCR_LOAD_FOUND);
        assert(record.sequence == 9 && record.state == BCR_PENDING);
        assert(!writes && !erases && !jumps);
        return 0;
    }
    if (!setjmp(done)) (void)bootloader_main();
    if (jumps != ((scenario == 2 || scenario == 6) ? 1U : 0U)) {
        fprintf(stderr, "scenario %u jumped %u times; I/O failures must remain in recovery\n", scenario, jumps);
        return 1;
    }
    assert(recovery == 4 && feeds == 3);
    assert(!writes && !erases);
    assert(reads[0] && reads[1]);
    if (scenario != 9) {
        bcr_record_t record, before;
        memset(&record, 0x5a, sizeof record); before=record;
        bcr_load_result_t result=bcr_load(&record);
        if (read_fail) assert(result == BCR_LOAD_IO_ERROR);
        else if (scenario == 2) assert(result == BCR_LOAD_ABSENT);
        else if (scenario == 3) assert(result == BCR_LOAD_INVALID);
        else assert(result == BCR_LOAD_FOUND);
        if (result != BCR_LOAD_FOUND) {
            assert(!memcmp(&record, &before, sizeof record));
            uint32_t floor=0x5a5a5a5a;
            assert(!boot_rollback_counter(&floor) && floor == 0x5a5a5a5a);
            image_manifest_t manifest={0};
            manifest.magic=IMAGE_MANIFEST_MAGIC;
            manifest.product_id=BOOTLOADER_PRODUCT_ID;
            manifest.body_size=4097;
            manifest.version=0xffffffffU;
            assert(verify_candidate(&manifest) == IMAGE_VERIFY_ROLLBACK);
        }
    }
    return 0;
}
'''


def test_bcr_read_failures_never_jump_or_mutate():
    compiler = shutil.which("gcc") or shutil.which("clang")
    assert compiler, "host C compiler is required"
    with tempfile.TemporaryDirectory(prefix="boot_bcr_failclosed_") as directory:
        temp = Path(directory)
        harness = temp / "harness.c"
        platform = (ROOT / "bootloader/src/platform_n32l406.c").read_text(encoding="utf-8")
        counter = platform[platform.index("bool boot_rollback_counter"):platform.index("void boot_jump_to")]
        hooks = """
void boot_bcr_retry_wait(uint32_t attempt, bool io_error) {(void)attempt;(void)io_error;}
void boot_startup_status(const char *stage, int32_t value) {(void)stage;(void)value;}
"""
        harness.write_text(HARNESS + "\n" + counter + hooks, encoding="ascii")
        common = [compiler, "-std=c99", "-O1", "-Wall", "-Wextra", "-Werror",
                  "-I", str(ROOT / "bootloader/include"), "-I", str(ROOT / "include")]
        main = temp / "main.o"
        result = subprocess.run(common + ["-Dmain=bootloader_main", "-c",
                                str(ROOT / "bootloader/src/main.c"), "-o", str(main)],
                                capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        exe = temp / "harness.exe"
        result = subprocess.run(common + [str(harness), str(main),
                                *[str(ROOT / "bootloader/src" / name) for name in
                                  ("bcr.c", "image_install.c", "image_verify.c")],
                                "-o", str(exe)], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        failures = []
        for scenario in range(10):
            for fault_reset in (0, 1):
                result = subprocess.run([str(exe), str(scenario), str(fault_reset)], capture_output=True, text=True)
                if result.returncode:
                    failures.append(f"scenario {scenario}, fault {fault_reset}: " + result.stdout + result.stderr)
        assert not failures, "\n".join(failures)


def test_bootloader_contract_uses_detached_authorization_and_32_byte_offset():
    verify = (ROOT / "bootloader/src/image_verify.c").read_text(encoding="utf-8")
    install = (ROOT / "bootloader/src/image_install.c").read_text(encoding="utf-8")
    assert "boot_authorization_load" in verify
    assert "FOTA_PACKAGE_HEADER_SIZE" in verify
    assert "CANDIDATE_BASE + FOTA_PACKAGE_HEADER_SIZE" in install
    assert "sizeof(image_manifest_t)" not in verify
    assert "sizeof(image_manifest_t)" not in install


if __name__ == "__main__":
    test_bcr_read_failures_never_jump_or_mutate()
    test_bootloader_contract_uses_detached_authorization_and_32_byte_offset()
    print("test_bootloader_bcr_failclosed: PASS (20 production C scenarios)")
