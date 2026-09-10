"""Exercise durable recovery when a Trial image cannot be entered."""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def test_trial_vector_rejection_persists_attempts_before_recovery():
    compiler = shutil.which("gcc") or shutil.which("clang")
    assert compiler, "host C compiler is required"
    harness = r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include "image_install.h"
#include "bcr.h"
#include "bootloader_config.h"

static bcr_record_t record;
static unsigned commits, jumps, restores;

bcr_load_result_t bcr_load(bcr_record_t *out) { *out = record; return BCR_LOAD_FOUND; }
bool bcr_commit(const bcr_record_t *in) { record = *in; ++commits; return true; }
bool bcr_valid(const bcr_record_t *in) { return in != 0; }
bool bcr_note_trial_reset(bool fault) { (void)fault; return true; }
bool bcr_mark_trial_healthy(void) { return false; }
bool boot_ext_read(uint32_t a, void *p, uint32_t n) { (void)a; (void)p; (void)n; return false; }
bool boot_ext_write(uint32_t a, const void *p, uint32_t n) { (void)a; (void)p; (void)n; return false; }
bool boot_ext_erase(uint32_t a, uint32_t n) { (void)a; (void)n; return false; }
bool boot_ext_is_complete(uint32_t a, uint32_t n) { (void)a; (void)n; return false; }
bool boot_int_flash_read(uint32_t a, void *p, uint32_t n) { (void)a; (void)p; (void)n; return false; }
bool boot_int_flash_program(uint32_t a, const void *p, uint32_t n) { (void)a; (void)p; (void)n; return false; }
bool boot_int_flash_erase(uint32_t a, uint32_t n) { (void)a; (void)n; ++restores; return false; }
bool verify_external_manifest(const image_manifest_t *m, uint32_t base, uint32_t auth) { (void)m; (void)base; (void)auth; return false; }
bool verify_external_manifest_for_promotion(const image_manifest_t *m, uint32_t base, uint32_t auth) { (void)m; (void)base; (void)auth; return false; }
bool verify_legacy_package(uint32_t base,uint32_t end,legacy_image_manifest_t*out){(void)base;(void)end;(void)out;return false;}
bool boot_authorization_load(fota_authorization_t*out){(void)out;return false;}
bool boot_authorization_read_at(uint32_t a,fota_authorization_t*out){(void)a;(void)out;return false;}
uint32_t image_crc32(const void*p,uint32_t n){(void)p;(void)n;return 0;}
image_verify_result_t verify_candidate(const image_manifest_t *m) { (void)m; return IMAGE_VERIFY_OK; }
void boot_jump_to(uint32_t address) { assert(address == APP_FLASH_BASE); ++jumps; }
bool boot_app_vectors_valid(uint32_t address) { (void)address; return false; }
void boot_watchdog_feed(void) {}

int main(void) {
    memset(&record, 0, sizeof record);
    record.state = BCR_TRIAL;
    record.boot_attempts = 0;
    assert(!bootloader_select_image());
    assert(record.boot_attempts == BOOTLOADER_TRIAL_LIMIT);
    assert(record.state == BCR_RECOVERY && jumps == 0 && commits == 2 && restores == 0);
    return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix="boot_invalid_vector_") as directory:
        temp = Path(directory)
        source = temp / "harness.c"
        executable = temp / "harness.exe"
        source.write_text(harness, encoding="ascii")
        command = [compiler, "-std=c99", "-O1", "-Wall", "-Wextra", "-Werror",
                   "-I", str(ROOT / "bootloader/include"), "-I", str(ROOT / "include"),
                   str(source), str(ROOT / "bootloader/src/image_install.c"), "-o", str(executable)]
        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        result = subprocess.run([str(executable)], capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr


if __name__ == "__main__":
    test_trial_vector_rejection_persists_attempts_before_recovery()
    print("test_bootloader_invalid_vector_recovery: PASS")
