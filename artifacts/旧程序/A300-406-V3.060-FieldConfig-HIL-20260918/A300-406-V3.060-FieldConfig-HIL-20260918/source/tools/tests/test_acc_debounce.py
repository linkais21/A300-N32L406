#!/usr/bin/env python3
"""Regression tests for PA12 ACC level debounce."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

HARNESS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include "work_mode.h"

static const work_mode_config_t CFG = {30U, 180U, 180U, 300U, 6U};

static void step_ms(uint32_t now_ms, bool raw_acc)
{
    work_mode_input_t in = {0};
    in.now_s = now_ms / 1000U;
    in.acc_high = raw_acc;
    in.gps_valid = true;
    in.vibration_sample_valid = false;
    work_mode_acc_sample(raw_acc, now_ms);
    work_mode_step(&in);
}

static void drain(void)
{
    work_mode_action_t action;
    while (work_mode_next_action(&action)) { }
}

static void test_low_glitch_does_not_enter_stop1(void)
{
    work_mode_init(&CFG, 1U, true);
    drain();
    step_ms(101U, false);
    assert(work_mode_state() == WORK_MODE_REALTIME);
    step_ms(121U, true); /* candidate low was only 20 ms */
    assert(work_mode_state() == WORK_MODE_REALTIME);
    assert(work_mode_logical_acc());
}

static void test_low_requires_500ms_confirmation(void)
{
    work_mode_init(&CFG, 1U, true);
    drain();
    step_ms(1U, false);
    step_ms(500U, false);
    assert(work_mode_state() == WORK_MODE_REALTIME);
    step_ms(501U, false);
    assert(work_mode_state() == WORK_MODE_STATIONARY_SLEEP);
    assert(!work_mode_logical_acc());
}

static void test_high_requires_500ms_confirmation_after_stop1(void)
{
    work_mode_init(&CFG, 1U, true);
    drain();
    step_ms(1U, false);
    step_ms(501U, false);
    assert(work_mode_state() == WORK_MODE_STATIONARY_SLEEP);
    drain();
    step_ms(1001U, true);
    assert(work_mode_state() == WORK_MODE_STATIONARY_SLEEP);
    step_ms(1500U, true);
    assert(work_mode_state() == WORK_MODE_STATIONARY_SLEEP);
    step_ms(1501U, true);
    assert(work_mode_state() == WORK_MODE_REALTIME);
    assert(work_mode_logical_acc());
}

int main(void)
{
    test_low_glitch_does_not_enter_stop1();
    test_low_requires_500ms_confirmation();
    test_high_requires_500ms_confirmation_after_stop1();
    return 0;
}
'''


def main() -> None:
    cc = os.environ.get("CC") or shutil.which("gcc") or shutil.which("cc")
    if not cc:
        raise AssertionError("host C compiler is required")
    with tempfile.TemporaryDirectory(prefix="acc_debounce_") as d:
        d = Path(d)
        harness = d / "harness.c"
        exe = d / "harness.exe"
        harness.write_text(HARNESS, encoding="ascii")
        built = subprocess.run(
            [cc, "-std=c99", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "include"),
             str(harness), str(ROOT / "src" / "work_mode.c"), "-o", str(exe)],
            cwd=ROOT, capture_output=True, text=True)
        if built.returncode:
            raise AssertionError("host build failed:\n" + built.stderr)
        run = subprocess.run([str(exe)], cwd=ROOT, capture_output=True, text=True)
        if run.returncode:
            raise AssertionError("ACC debounce regression failed:\n" + run.stderr)
    print("ACC debounce: PASS")


if __name__ == "__main__":
    main()
