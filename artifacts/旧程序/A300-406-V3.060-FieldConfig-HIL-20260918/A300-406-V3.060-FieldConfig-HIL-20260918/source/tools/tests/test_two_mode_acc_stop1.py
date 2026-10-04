#!/usr/bin/env python3
"""Executable regression contracts for the confirmed ACC/STOP1 policy.

These tests intentionally describe the final two-mode contract.  They are
expected to expose RED failures until the work-mode and hardware polarity
implementation is updated.
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

HARNESS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include "work_mode.h"

static const work_mode_config_t CFG = {
    .report_moving_s = 30U,
    .report_stopped_s = 180U,
    .heartbeat_s = 180U,
    .stationary_timeout_s = 300U,
    .vibration_confirm_s = 6U
};

static void step(uint32_t now_s, bool acc_high, bool vibration,
                 uint32_t alarm_bits)
{
    work_mode_input_t in = {
        .now_s = now_s,
        .acc_high = acc_high,
        .vibration_hit = vibration,
        .rtc_wake = false,
        .alarm_bits = alarm_bits,
        .gps_valid = true,
        .vibration_sample_valid = true
    };
    work_mode_step(&in);
}

static size_t drain(work_mode_action_t *out, size_t cap)
{
    size_t n = 0U;
    while (n < cap && work_mode_next_action(&out[n])) ++n;
    return n;
}

static bool has_action(const work_mode_action_t *a, size_t n,
                       work_mode_action_type_t type, bool acc_on)
{
    size_t i;
    for (i = 0U; i < n; ++i)
        if (a[i].type == type && a[i].acc_on == acc_on) return true;
    return false;
}

static size_t count_action(const work_mode_action_t *a, size_t n,
                           work_mode_action_type_t type)
{
    size_t i;
    size_t count = 0U;
    for (i = 0U; i < n; ++i)
        if (a[i].type == type) ++count;
    return count;
}

static void enter_stop1(void)
{
    work_mode_action_t a[12];
    work_mode_init(&CFG, 0U, false);
    (void)drain(a, sizeof(a) / sizeof(a[0]));
    step(300U, false, false, 0U);
    assert(work_mode_state() == WORK_MODE_STATIONARY_SLEEP);
    (void)drain(a, sizeof(a) / sizeof(a[0]));
}

static void test_boot_off_starts_with_immediate_acc_on_location(void)
{
    work_mode_action_t a[8];
    size_t n;
    work_mode_init(&CFG, 0U, false);
    n = drain(a, sizeof(a) / sizeof(a[0]));
    /* Boot window is logically ON and must send an immediate 0x0200. */
    assert(has_action(a, n, WORK_ACTION_SET_LOGICAL_ACC, true));
    assert(has_action(a, n, WORK_ACTION_REPORT_ENTRY, true));
    assert(work_mode_state() == WORK_MODE_BOOT_MONITOR);
}

static void test_boot_static_transitions_once_after_five_minutes(void)
{
    work_mode_action_t a[12];
    size_t n;
    work_mode_init(&CFG, 100U, false);
    (void)drain(a, sizeof(a) / sizeof(a[0]));
    step(399U, false, false, 0U);
    assert(work_mode_state() == WORK_MODE_BOOT_MONITOR);
    step(400U, false, false, 0U);
    assert(work_mode_state() == WORK_MODE_STATIONARY_SLEEP);
    n = drain(a, sizeof(a) / sizeof(a[0]));
    assert(has_action(a, n, WORK_ACTION_REPORT_ENTRY, false));
    assert(count_action(a, n, WORK_ACTION_GPS_OFF) == 1U);
    assert(count_action(a, n, WORK_ACTION_ENTER_STOP1) == 1U);
    step(401U, false, false, 0U);
    n = drain(a, sizeof(a) / sizeof(a[0]));
    assert(!has_action(a, n, WORK_ACTION_REPORT_ENTRY, false));
    assert(!has_action(a, n, WORK_ACTION_GPS_OFF, false));
    assert(!has_action(a, n, WORK_ACTION_ENTER_STOP1, false));
}

static void test_acc_rising_edge_wakes_stop1(void)
{
    work_mode_action_t a[12];
    size_t n;
    enter_stop1();
    step(301U, true, false, 0U);
    assert(work_mode_state() == WORK_MODE_REALTIME);
    n = drain(a, sizeof(a) / sizeof(a[0]));
    assert(has_action(a, n, WORK_ACTION_SET_LOGICAL_ACC, true));
    assert(has_action(a, n, WORK_ACTION_REPORT_ENTRY, true));
    assert(count_action(a, n, WORK_ACTION_GPS_ON) == 1U);
}

static void test_alarm_wakes_stop1_into_realtime(void)
{
    work_mode_action_t a[12];
    size_t n;
    enter_stop1();
    step(301U, false, false, 1U);
    assert(work_mode_state() == WORK_MODE_REALTIME);
    n = drain(a, sizeof(a) / sizeof(a[0]));
    assert(has_action(a, n, WORK_ACTION_SET_LOGICAL_ACC, true));
    assert(has_action(a, n, WORK_ACTION_REPORT_ENTRY, true));
    assert(count_action(a, n, WORK_ACTION_GPS_ON) == 1U);
}

static void test_sustained_vibration_wakes_stop1_into_realtime(void)
{
    work_mode_action_t a[16];
    size_t n;
    uint32_t i;
    enter_stop1();
    /* DA218E samples arrive every 200 ms: 29 hits (5.8 s) stay asleep. */
    for (i = 0U; i < 29U; ++i) step(301U + (i / 5U), false, true, 0U);
    assert(work_mode_state() == WORK_MODE_STATIONARY_SLEEP);
    /* A single missed sample is tolerated while the physical vibration
     * continues; confirmation remains on the same six-second episode. */
    step(306U, false, false, 0U);
    assert(work_mode_state() == WORK_MODE_STATIONARY_SLEEP);
    for (i = 0U; i < 4U; ++i) step(306U + (i / 5U), false, true, 0U);
    step(307U, false, true, 0U);
    assert(work_mode_state() == WORK_MODE_REALTIME);
    n = drain(a, sizeof(a) / sizeof(a[0]));
    assert(has_action(a, n, WORK_ACTION_SET_LOGICAL_ACC, true));
    assert(has_action(a, n, WORK_ACTION_REPORT_ENTRY, true));
    assert(count_action(a, n, WORK_ACTION_GPS_ON) == 1U);
}

static void test_stop1_dual_180_second_cadence(void)
{
    work_mode_action_t a[12];
    size_t n;
    enter_stop1();
    step(480U, false, false, 0U);
    n = drain(a, sizeof(a) / sizeof(a[0]));
    assert(has_action(a, n, WORK_ACTION_REPORT_LOCATION, false));
    /* Heartbeat is owned by jt808_process to avoid duplicate 0x0002 frames. */
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    if (strcmp(argv[1], "boot_immediate") == 0)
        test_boot_off_starts_with_immediate_acc_on_location();
    else if (strcmp(argv[1], "boot_timeout_once") == 0)
        test_boot_static_transitions_once_after_five_minutes();
    else if (strcmp(argv[1], "acc_wake") == 0)
        test_acc_rising_edge_wakes_stop1();
    else if (strcmp(argv[1], "alarm_wake") == 0)
        test_alarm_wakes_stop1_into_realtime();
    else if (strcmp(argv[1], "vibration_wake") == 0)
        test_sustained_vibration_wakes_stop1_into_realtime();
    else if (strcmp(argv[1], "stop1_cadence") == 0)
        test_stop1_dual_180_second_cadence();
    else
        assert(!"unknown test case");
    return 0;
}
'''


def main() -> int:
    cc = os.environ.get("CC") or shutil.which("gcc") or shutil.which("cc")
    if not cc:
        raise AssertionError("two-mode ACC/STOP1: host C compiler is required")
    with tempfile.TemporaryDirectory(prefix="two_mode_acc_stop1_") as d:
        d = Path(d)
        harness = d / "harness.c"
        executable = d / "harness.exe"
        harness.write_text(HARNESS, encoding="ascii")
        cmd = [cc, "-std=c99", "-Wall", "-Wextra", "-Werror",
               "-I", str(ROOT / "include"), str(harness),
               str(ROOT / "src" / "work_mode.c"), "-o", str(executable)]
        built = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        if built.returncode:
            raise AssertionError("host build failed:\n" + built.stderr)
        failures = []
        cases = ["boot_immediate", "boot_timeout_once", "acc_wake",
                 "alarm_wake", "vibration_wake", "stop1_cadence"]
        for case in cases:
            run = subprocess.run([str(executable), case], cwd=ROOT,
                                 capture_output=True, text=True)
            if run.returncode:
                failures.append(f"{case}: {run.stderr.strip()}")
        if failures:
            raise AssertionError("two-mode ACC/STOP1 contract failed:\n" +
                                 "\n".join(failures))
    print("two-mode ACC/STOP1 contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
