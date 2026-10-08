"""Regression coverage for vibration wake confirmation and re-arming."""

from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "src" / "i2c_accel.c").read_text(encoding="utf-8")
HEADER = (ROOT / "include" / "i2c_accel.h").read_text(encoding="utf-8")
MAIN = (ROOT / "src" / "main.c").read_text(encoding="utf-8")

HARNESS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include "work_mode.h"

static const work_mode_config_t CFG = { 30U, 180U, 180U, 300U, 6U };

static void step_ms(uint32_t now_ms, bool hit)
{
    work_mode_input_t in = {
        .now_s = now_ms / 1000U,
        .now_ms = now_ms,
        .acc_high = false,
        .vibration_hit = hit,
        .rtc_wake = false,
        .alarm_bits = 0U,
        .gps_valid = true,
        .vibration_sample_valid = true,
    };
    work_mode_step(&in);
}

static void drain(void)
{
    work_mode_action_t action;
    while (work_mode_next_action(&action)) {}
}

static void enter_stationary(void)
{
    work_mode_init(&CFG, 0U, false);
    drain();
    step_ms(300000U, false);
    assert(work_mode_state() == WORK_MODE_STATIONARY_SLEEP);
    drain();
}

static unsigned count_realtime_entries(void)
{
    work_mode_action_t action;
    unsigned count = 0U;
    while (work_mode_next_action(&action)) {
        if (action.type == WORK_ACTION_REPORT_ENTRY && action.acc_on)
            ++count;
    }
    return count;
}

static void exact_six_seconds_with_two_consecutive_misses(void)
{
    uint32_t t;
    enter_stationary();
    for (t = 300200U; t <= 306200U; t += 200U)
        step_ms(t, t != 302200U && t != 302400U);
    assert(work_mode_state() == WORK_MODE_REALTIME);
}

static void exact_six_seconds_with_two_separated_misses(void)
{
    uint32_t t;
    enter_stationary();
    for (t = 300200U; t <= 306200U; t += 200U)
        step_ms(t, t != 301200U && t != 304200U);
    assert(work_mode_state() == WORK_MODE_REALTIME);
}

static void scheduler_jitter_uses_elapsed_time(void)
{
    uint32_t t;
    enter_stationary();
    for (t = 300200U; t <= 306200U; t += 250U)
        step_ms(t, true);
    assert(work_mode_state() == WORK_MODE_REALTIME);
}

static void slow_cooperative_loop_uses_observed_sample_ratio(void)
{
    uint32_t t;
    enter_stationary();
    for (t = 300200U; t <= 306200U; t += 400U)
        step_ms(t, true);
    assert(work_mode_state() == WORK_MODE_REALTIME);
}

static void over_one_second_quiet_requires_a_new_six_seconds(void)
{
    uint32_t t;
    enter_stationary();
    step_ms(300200U, true);
    step_ms(300400U, false);
    step_ms(300600U, false);
    step_ms(300800U, false);
    step_ms(301000U, false);
    step_ms(301200U, false);
    step_ms(301400U, false);
    for (t = 301600U; t < 307600U; t += 200U)
        step_ms(t, true);
    assert(work_mode_state() == WORK_MODE_STATIONARY_SLEEP);
    step_ms(307600U, true);
    assert(work_mode_state() == WORK_MODE_REALTIME);
}

static void sparse_hits_do_not_accumulate_across_windows(void)
{
    uint32_t t;
    enter_stationary();
    for (t = 300200U; t <= 312200U; t += 200U)
        step_ms(t, (t % 600U) == 200U);
    assert(work_mode_state() == WORK_MODE_STATIONARY_SLEEP);
}

static void confirmation_latches_one_realtime_entry(void)
{
    uint32_t t;
    enter_stationary();
    for (t = 300200U; t <= 306200U; t += 200U)
        step_ms(t, true);
    assert(count_realtime_entries() == 1U);
    for (t = 306400U; t <= 308000U; t += 200U)
        step_ms(t, true);
    assert(count_realtime_entries() == 0U);
}

static void realtime_holds_for_full_stationary_timeout(void)
{
    uint32_t t;
    enter_stationary();
    for (t = 300200U; t <= 306200U; t += 200U)
        step_ms(t, true);
    step_ms(605999U, false);
    assert(work_mode_state() == WORK_MODE_REALTIME);
    step_ms(606200U, false);
    assert(work_mode_state() == WORK_MODE_STATIONARY_SLEEP);
}

static void later_motion_extends_realtime_hold(void)
{
    uint32_t t;
    enter_stationary();
    for (t = 300200U; t <= 306200U; t += 200U)
        step_ms(t, true);
    step_ms(500000U, true);
    step_ms(606200U, false);
    assert(work_mode_state() == WORK_MODE_REALTIME);
    step_ms(800000U, false);
    assert(work_mode_state() == WORK_MODE_STATIONARY_SLEEP);
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    if (strcmp(argv[1], "two_consecutive") == 0)
        exact_six_seconds_with_two_consecutive_misses();
    else if (strcmp(argv[1], "two_separated") == 0)
        exact_six_seconds_with_two_separated_misses();
    else if (strcmp(argv[1], "jitter") == 0)
        scheduler_jitter_uses_elapsed_time();
    else if (strcmp(argv[1], "slow_loop") == 0)
        slow_cooperative_loop_uses_observed_sample_ratio();
    else if (strcmp(argv[1], "quiet_gap") == 0)
        over_one_second_quiet_requires_a_new_six_seconds();
    else if (strcmp(argv[1], "sparse_long") == 0)
        sparse_hits_do_not_accumulate_across_windows();
    else if (strcmp(argv[1], "one_entry") == 0)
        confirmation_latches_one_realtime_entry();
    else if (strcmp(argv[1], "hold") == 0)
        realtime_holds_for_full_stationary_timeout();
    else if (strcmp(argv[1], "extend") == 0)
        later_motion_extends_realtime_hold();
    else
        assert(!"unknown case");
    return 0;
}
'''


class VibrationPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        compiler = os.environ.get("CC") or shutil.which("gcc") or shutil.which("cc")
        if not compiler:
            raise AssertionError("host C compiler is required")
        cls.temp = tempfile.TemporaryDirectory(prefix="vibration_wake_")
        directory = Path(cls.temp.name)
        harness = directory / "harness.c"
        cls.executable = directory / "harness.exe"
        harness.write_text(HARNESS, encoding="ascii")
        built = subprocess.run(
            [compiler, "-std=c99", "-Wall", "-Wextra", "-Werror",
             "-I", str(ROOT / "include"), str(harness),
             str(ROOT / "src" / "work_mode.c"), "-o", str(cls.executable)],
            cwd=ROOT, capture_output=True, text=True,
        )
        if built.returncode:
            raise AssertionError("vibration harness build failed:\n" + built.stderr)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def run_case(self, name: str) -> None:
        run = subprocess.run(
            [str(self.executable), name], cwd=ROOT, capture_output=True, text=True
        )
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_01_exact_six_seconds_allows_two_consecutive_misses(self) -> None:
        self.run_case("two_consecutive")

    def test_02_exact_six_seconds_allows_two_separated_misses(self) -> None:
        self.run_case("two_separated")

    def test_03_confirmation_uses_elapsed_time_under_scheduler_jitter(self) -> None:
        self.run_case("jitter")

    def test_04_over_one_second_quiet_resets_the_episode(self) -> None:
        self.run_case("quiet_gap")

    def test_03b_slow_loop_uses_observed_sample_ratio(self) -> None:
        self.run_case("slow_loop")

    def test_05_sparse_hits_do_not_accumulate_across_six_second_windows(self) -> None:
        self.run_case("sparse_long")

    def test_06_confirmed_episode_queues_one_realtime_entry(self) -> None:
        self.run_case("one_entry")

    def test_07_realtime_holds_for_the_full_stationary_timeout(self) -> None:
        self.run_case("hold")

    def test_08_later_motion_extends_realtime_hold(self) -> None:
        self.run_case("extend")


class VibrationInterruptTests(unittest.TestCase):
    def test_09_da218e_interrupt_is_single_event_latched(self) -> None:
        self.assertRegex(
            SOURCE, r"\{DA218E_REG_INT_LATCH,\s*0x07U\}",
        )

    def test_10_driver_exposes_bounded_interrupt_rearm(self) -> None:
        self.assertRegex(
            HEADER, r"bool\s+i2c_accel_rearm_wake_interrupt\(void\);",
        )
        match = re.search(
            r"bool\s+i2c_accel_rearm_wake_interrupt\s*\(\s*void\s*\)\s*\{(.*?)\n\}",
            SOURCE, re.DOTALL,
        )
        self.assertIsNotNone(match)
        body = match.group(1)
        self.assertRegex(body, r"i2c_write_reg\(DA218E_REG_INT_CONFIG,\s*0x81U\)")
        self.assertRegex(body, r"i2c_write_reg\(DA218E_REG_INT_CONFIG,\s*0x01U\)")
        self.assertIn("return false", body)

    def test_11_main_rearms_after_each_consumed_wake_window(self) -> None:
        close = MAIN.index("vibration_wake_window = false;")
        helper = MAIN.index("static void vibration_rearm_process")
        self.assertIn("i2c_accel_rearm_wake_interrupt()", MAIN[helper:close])

    def test_12_rearm_failure_is_bounded_and_blocks_sleep(self) -> None:
        self.assertIn("vibration_rearm_pending", MAIN)
        self.assertIn("vibration_rearm_attempts", MAIN)
        self.assertIn("vibration_rearm_fault", MAIN)
        self.assertRegex(MAIN, r"vibration_rearm_attempts\s*<\s*VIBRATION_REARM_MAX_ATTEMPTS")
        self.assertRegex(MAIN, r"s_vibration_rearm_pending\s*=\s*false")

    def test_13_sleep_admission_does_not_clear_a_newly_latched_event(self) -> None:
        sleep = (ROOT / "src" / "work_mode_sleep.c").read_text(encoding="utf-8")
        self.assertNotIn("i2c_accel_rearm_wake_interrupt()", sleep)
        self.assertRegex(
            MAIN,
            r"else if \(s_vibration_rearm_fault\) \{[\s\S]{0,300}?"
            r"s_shallow_sleep_allowed\s*=\s*true;",
        )
        self.assertRegex(
            MAIN,
            r"static void idle_sleep_process\(void\)\s*\{[\s\S]{0,300}?"
            r"if \(s_shallow_sleep_allowed\)\s*"
            r"work_mode_sleep_shallow\(\);",
        )

    def test_14_pending_rearm_retries_on_later_main_loop_passes(self) -> None:
        close = MAIN.index("vibration_wake_window = false;")
        retry = MAIN.index("if (s_vibration_rearm_pending)", close)
        self.assertIn("vibration_rearm_process()", MAIN[retry:retry + 128])

    def test_15_startup_configuration_failure_forces_shallow_fallback(self) -> None:
        self.assertRegex(
            MAIN,
            r"i2c_accel_init\(\);[\s\S]{0,300}?"
            r"s_vibration_rearm_fault\s*=\s*"
            r"!i2c_accel_get_diag\(\)->int1_rearm_ok;",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
