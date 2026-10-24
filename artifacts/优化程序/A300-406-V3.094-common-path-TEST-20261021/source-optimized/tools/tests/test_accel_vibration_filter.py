"""Host regression tests for the G452-compatible vibration detector."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]

HARNESS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "accel_vibration_filter.h"
#include "work_mode.h"

static const work_mode_config_t CFG = { 30U, 180U, 180U, 300U, 6U };

static void drain_actions(void)
{
    work_mode_action_t action;
    while (work_mode_next_action(&action)) {}
}

static void work_step(uint32_t now_ms, bool sample_valid, bool hit)
{
    work_mode_input_t input = {
        .now_s = now_ms / 1000U,
        .now_ms = now_ms,
        .acc_high = false,
        .vibration_hit = hit,
        .rtc_wake = false,
        .alarm_bits = 0U,
        .gps_valid = true,
        .vibration_sample_valid = sample_valid,
    };
    work_mode_step(&input);
}

static void enter_stationary(void)
{
    work_mode_init(&CFG, 0U, false);
    drain_actions();
    work_step(300000U, true, false);
    assert(work_mode_state() == WORK_MODE_STATIONARY_SLEEP);
    drain_actions();
}

static void max_axis_does_not_sum_subthreshold_noise(void)
{
    accel_vibration_filter_t filter;
    uint16_t motion = UINT16_MAX;

    accel_vibration_filter_reset(&filter);
    assert(!accel_vibration_filter_step(&filter, 0, 0, 0, 150U, &motion));
    assert(motion == 0U);
    assert(!accel_vibration_filter_step(
        &filter, 100, 100, 100, 150U, &motion));
    assert(motion == 100U);
}

static void one_axis_above_threshold_is_a_hit(void)
{
    accel_vibration_filter_t filter;
    uint16_t motion = 0U;

    accel_vibration_filter_reset(&filter);
    assert(!accel_vibration_filter_step(&filter, 0, 0, 0, 150U, &motion));
    assert(accel_vibration_filter_step(&filter, 200, 0, 0, 150U, &motion));
    assert(motion == 200U);
}

static void zero_baseline_recovery_does_not_wake(void)
{
    accel_vibration_filter_t filter;
    uint16_t motion;
    uint32_t sample;
    bool hit;

    enter_stationary();
    accel_vibration_filter_reset(&filter);
    hit = accel_vibration_filter_step(&filter, 0, 0, 0, 150U, &motion);
    work_step(300000U, true, hit);
    for (sample = 1U; sample <= 35U; ++sample) {
        hit = accel_vibration_filter_step(
            &filter, -40, 10, 1000, 150U, &motion);
        work_step(300000U + sample * 200U, true, hit);
    }
    assert(work_mode_state() == WORK_MODE_STATIONARY_SLEEP);
}

static void sustained_vibration_still_wakes_after_six_seconds(void)
{
    accel_vibration_filter_t filter;
    uint16_t motion;
    uint32_t sample;
    bool hit;

    enter_stationary();
    accel_vibration_filter_reset(&filter);
    hit = accel_vibration_filter_step(&filter, 0, 0, 1000, 150U, &motion);
    work_step(300000U, true, hit);
    for (sample = 1U; sample <= 31U; ++sample) {
        int16_t z = (sample & 1U) != 0U ? 750 : 1250;
        hit = accel_vibration_filter_step(&filter, 0, 0, z, 150U, &motion);
        work_step(300000U + sample * 200U, true, hit);
    }
    assert(work_mode_state() == WORK_MODE_REALTIME);
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    if (strcmp(argv[1], "max_axis") == 0)
        max_axis_does_not_sum_subthreshold_noise();
    else if (strcmp(argv[1], "one_axis") == 0)
        one_axis_above_threshold_is_a_hit();
    else if (strcmp(argv[1], "zero_recovery") == 0)
        zero_baseline_recovery_does_not_wake();
    else if (strcmp(argv[1], "sustained") == 0)
        sustained_vibration_still_wakes_after_six_seconds();
    else
        assert(!"unknown test case");
    return 0;
}
'''


class AccelVibrationFilterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        compiler = os.environ.get("CC") or shutil.which("gcc") or shutil.which("cc")
        if not compiler:
            raise AssertionError("host C compiler is required")
        cls.temp = tempfile.TemporaryDirectory(prefix="accel_vibration_filter_")
        directory = Path(cls.temp.name)
        harness = directory / "harness.c"
        cls.executable = directory / "harness.exe"
        harness.write_text(HARNESS, encoding="ascii")
        built = subprocess.run(
            [
                compiler,
                "-std=c99",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-I",
                str(ROOT / "include"),
                str(harness),
                str(ROOT / "src" / "accel_vibration_filter.c"),
                str(ROOT / "src" / "work_mode.c"),
                "-o",
                str(cls.executable),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if built.returncode:
            raise AssertionError("vibration filter harness build failed:\n" + built.stderr)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def run_case(self, name: str) -> None:
        run = subprocess.run(
            [str(self.executable), name], cwd=ROOT, capture_output=True, text=True
        )
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_max_axis_does_not_sum_subthreshold_noise(self) -> None:
        self.run_case("max_axis")

    def test_one_axis_above_threshold_is_a_hit(self) -> None:
        self.run_case("one_axis")

    def test_zero_baseline_recovery_does_not_wake(self) -> None:
        self.run_case("zero_recovery")

    def test_sustained_vibration_still_wakes_after_six_seconds(self) -> None:
        self.run_case("sustained")


if __name__ == "__main__":
    unittest.main(verbosity=2)
