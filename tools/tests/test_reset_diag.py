"""Host regression for RTC-backup watchdog and HardFault diagnostics."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import re


ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "src" / "main.c").read_text(encoding="utf-8")

HARNESS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "reset_diag.h"

static uint32_t backup[RESET_DIAG_BACKUP_WORDS];
static uint8_t reset_flags;

uint32_t reset_diag_host_backup_read(uint8_t index)
{
    assert(index < RESET_DIAG_BACKUP_WORDS);
    return backup[index];
}

void reset_diag_host_backup_write(uint8_t index, uint32_t value)
{
    assert(index < RESET_DIAG_BACKUP_WORDS);
    backup[index] = value;
}

uint8_t reset_diag_host_reset_flags(void) { return reset_flags; }
void reset_diag_host_clear_reset_flags(void) { reset_flags = 0U; }
void reset_diag_host_enable_backup_access(void) {}

static void reboot(uint8_t flags)
{
    reset_flags = flags;
    reset_diag_capture();
    reset_diag_runtime_init();
}

static void test_invalid_record_is_ignored(void)
{
    reset_diag_snapshot_t snapshot;
    memset(backup, 0xA5, sizeof backup);
    reboot(RESET_FLAG_POWER_ON);
    assert(!reset_diag_previous(&snapshot));
    assert(reset_diag_reason() == RESET_REASON_POWER_ON);
}

static void test_iwdg_preserves_phase_and_sequence(void)
{
    reset_diag_snapshot_t snapshot;
    memset(backup, 0, sizeof backup);
    reboot(RESET_FLAG_POWER_ON);
    reset_diag_loop_begin();
    reset_diag_mark_phase(RESET_DIAG_PHASE_TCP_MANAGER);
    reset_diag_loop_begin();
    reset_diag_mark_phase(RESET_DIAG_PHASE_JT808);

    reboot(RESET_FLAG_IWDG | RESET_FLAG_PIN);
    assert(reset_diag_previous(&snapshot));
    assert(snapshot.phase == RESET_DIAG_PHASE_JT808);
    assert(snapshot.loop_sequence == 2U);
    assert(!snapshot.hardfault);
    assert(reset_diag_reason() == RESET_REASON_IWDG);
    assert(reset_diag_raw_flags() == (RESET_FLAG_IWDG | RESET_FLAG_PIN));

    reset_diag_loop_begin();
    reset_diag_mark_phase(RESET_DIAG_PHASE_GPS);
    reboot(RESET_FLAG_IWDG);
    assert(reset_diag_previous(&snapshot));
    assert(snapshot.phase == RESET_DIAG_PHASE_GPS);
    assert(snapshot.loop_sequence == 1U);
}

static void test_hardfault_context_is_committed(void)
{
    reset_diag_snapshot_t snapshot;
    reset_diag_record_fault(0x08012345U, 0x08005679U,
                            0x00008200U, 0x40000000U);
    reboot(RESET_FLAG_IWDG);
    assert(reset_diag_previous(&snapshot));
    assert(snapshot.hardfault);
    assert(snapshot.pc == 0x08012345U);
    assert(snapshot.lr == 0x08005679U);
    assert(snapshot.cfsr == 0x00008200U);
    assert(snapshot.hfsr == 0x40000000U);

    reboot(RESET_FLAG_SOFTWARE);
    assert(reset_diag_previous(&snapshot));
    assert(!snapshot.hardfault);
    assert(snapshot.pc == 0U && snapshot.lr == 0U);
}

static void test_early_hardfault_survives_software_reset(void)
{
    reset_diag_snapshot_t snapshot;
    reboot(RESET_FLAG_POWER_ON);
    reset_diag_record_fault(0x0800A001U, 0x0800B003U,
                            0x00010000U, 0x40000000U);
    reboot(RESET_FLAG_SOFTWARE);
    assert(reset_diag_previous(&snapshot));
    assert(snapshot.hardfault);
    assert(snapshot.pc == 0x0800A001U);
    assert(snapshot.lr == 0x0800B003U);
}

static void test_corrupt_complement_is_rejected(void)
{
    reset_diag_snapshot_t snapshot;
    reset_diag_loop_begin();
    reset_diag_mark_phase(RESET_DIAG_PHASE_FOTA);
    backup[RESET_DIAG_WORD_PHASE] ^= 0x00010000U;
    reboot(RESET_FLAG_IWDG);
    assert(!reset_diag_previous(&snapshot));
}

int main(void)
{
    test_invalid_record_is_ignored();
    test_iwdg_preserves_phase_and_sequence();
    test_hardfault_context_is_committed();
    test_early_hardfault_survives_software_reset();
    test_corrupt_complement_is_rejected();
    assert(strcmp(reset_diag_phase_name(RESET_DIAG_PHASE_TCP_MANAGER),
                  "tcp") == 0);
    puts("test_reset_diag: PASS");
    return 0;
}
'''


def compiler() -> str:
    cc = os.environ.get("CC") or shutil.which("gcc") or shutil.which("cc")
    if not cc:
        raise AssertionError("host C compiler is required")
    return cc


def main() -> None:
    assert re.search(
        r"if\s*\(\s*!s_iwdg_started\s*\)\s*NVIC_SystemReset\(\);",
        MAIN,
    ), "an early HardFault must reset even before IWDG is enabled"
    assert re.search(
        r"reset_diag_previous\(&previous\)[\s\S]{0,200}?previous\.hardfault",
        MAIN,
    ), "a software-reset HardFault snapshot must be printed at boot"
    with tempfile.TemporaryDirectory(prefix="reset_diag_") as td:
        directory = Path(td)
        harness = directory / "harness.c"
        output = directory / "reset_diag.exe"
        harness.write_text(HARNESS, encoding="ascii")
        build = subprocess.run(
            [compiler(), "-std=c99", "-Wall", "-Wextra", "-Werror",
             "-DRESET_DIAG_HOST_TEST", "-I", str(ROOT / "include"),
             str(harness), str(ROOT / "src" / "reset_diag.c"),
             "-o", str(output)],
            cwd=ROOT, capture_output=True, text=True,
        )
        if build.returncode:
            raise AssertionError("reset diagnostic harness compile failed:\n" +
                                 build.stdout + build.stderr)
        run = subprocess.run([str(output)], cwd=ROOT,
                             capture_output=True, text=True)
        if run.returncode:
            raise AssertionError("reset diagnostic harness failed:\n" +
                                 run.stdout + run.stderr)
        print(run.stdout.strip())


if __name__ == "__main__":
    main()
