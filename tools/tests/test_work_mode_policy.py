"""Host regression tests for the pure A300 work-mode policy.

Each assertion exercises the real C policy through a small host harness.  The
breaks protected here are wrong transition priority, deadline coupling, and an
unbounded action backlog.
"""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]

HARNESS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>

#include "work_mode.h"

#define ARRAY_LEN(a) (sizeof(a) / sizeof((a)[0]))

static const work_mode_config_t DEFAULT_CONFIG = {
    30U, 180U, 180U, 300U, 6U
};

static void step(uint32_t now_s, bool acc_high, bool vibration_hit,
                 uint32_t alarm_bits, bool gps_valid)
{
    work_mode_input_t input = {
        .now_s = now_s,
        .acc_high = acc_high,
        .vibration_hit = vibration_hit,
        .rtc_wake = false,
        .alarm_bits = alarm_bits,
        .gps_valid = gps_valid,
        .vibration_sample_valid = true,
        .now_ms = 0U
    };
    work_mode_step(&input);
}

static void step_ms(uint32_t now_ms, bool acc_high, bool vibration_hit)
{
    work_mode_input_t input = {
        .now_s = now_ms / 1000U,
        .acc_high = acc_high,
        .vibration_hit = vibration_hit,
        .rtc_wake = false,
        .alarm_bits = 0U,
        .gps_valid = false,
        .vibration_sample_valid = true,
        .now_ms = now_ms
    };
    work_mode_step(&input);
}

static size_t drain(work_mode_action_t *actions, size_t capacity)
{
    size_t count = 0U;
    while (count < capacity && work_mode_next_action(&actions[count])) {
        ++count;
    }
    return count;
}

static void assert_actions(const work_mode_action_type_t *want, size_t want_count)
{
    work_mode_action_t got[20];
    size_t i;
    size_t count = drain(got, ARRAY_LEN(got));

    assert(count == want_count);
    for (i = 0U; i < count; ++i) {
        assert(got[i].type == want[i]);
    }
}

static void enter_stationary(uint32_t now_s)
{
    static const work_mode_action_type_t expected[] = {
        WORK_ACTION_SET_LOGICAL_ACC, WORK_ACTION_GPS_OFF,
        WORK_ACTION_REPORT_ENTRY, WORK_ACTION_ENTER_STOP1
    };
    work_mode_action_t discarded[4];
    work_mode_init(&DEFAULT_CONFIG, now_s, true);
    assert(drain(discarded, ARRAY_LEN(discarded)) == 3U);
    step(now_s, false, false, 0U, false);
    assert(work_mode_state() == WORK_MODE_STATIONARY_SLEEP);
    assert(!work_mode_logical_acc());
    assert_actions(expected, ARRAY_LEN(expected));
}

static void test_pa12_high_boot_enters_realtime_once(void)
{
    static const work_mode_action_type_t expected[] = {
        WORK_ACTION_SET_LOGICAL_ACC, WORK_ACTION_GPS_ON, WORK_ACTION_REPORT_ENTRY
    };
    work_mode_init(&DEFAULT_CONFIG, 10U, true);
    assert(work_mode_state() == WORK_MODE_REALTIME);
    assert(work_mode_logical_acc());
    assert_actions(expected, ARRAY_LEN(expected));
    step(11U, true, false, 0U, true);
    assert_actions((const work_mode_action_type_t[]){}, 0U);
}

static void test_pa12_low_to_high_enters_realtime_and_sets_acc_on(void)
{
    work_mode_action_t actions[8];
    size_t count;
    size_t i;
    bool saw_acc_on = false;
    work_mode_init(&DEFAULT_CONFIG, 0U, false);
    step(1U, true, false, 0U, true);
    assert(work_mode_state() == WORK_MODE_REALTIME);
    count = drain(actions, ARRAY_LEN(actions));
    for (i = 0U; i < count; ++i) {
        if (actions[i].type == WORK_ACTION_SET_LOGICAL_ACC && actions[i].acc_on)
            saw_acc_on = true;
    }
    assert(saw_acc_on);
    assert(work_mode_logical_acc());
}

static void test_pa12_low_without_vibration_sleeps_after_five_minutes(void)
{
    work_mode_init(&DEFAULT_CONFIG, 100U, false);
    step(399U, false, false, 0U, true);
    assert(work_mode_state() == WORK_MODE_BOOT_MONITOR);
    step(400U, false, false, 0U, true);
    assert(work_mode_state() == WORK_MODE_STATIONARY_SLEEP);
}

static void test_boot_monitor_waits_indefinitely_without_gps_fix(void)
{
    /* A slow cold start (no fix yet) must not let the boot-monitor deadline
     * power GNSS down: retry indefinitely rather than going dark. */
    work_mode_init(&DEFAULT_CONFIG, 100U, false);
    step(400U, false, false, 0U, false);
    assert(work_mode_state() == WORK_MODE_BOOT_MONITOR);
    step(10000U, false, false, 0U, false);
    assert(work_mode_state() == WORK_MODE_BOOT_MONITOR);
    step(10001U, false, false, 0U, true);
    assert(work_mode_state() == WORK_MODE_STATIONARY_SLEEP);
}

static void test_boot_monitor_reports_acc_on_every_moving_interval(void)
{
    work_mode_action_t action;

    work_mode_init(&DEFAULT_CONFIG, 0U, false);
    assert(work_mode_logical_acc());
    assert(work_mode_next_action(&action));
    assert(action.type == WORK_ACTION_SET_LOGICAL_ACC);
    assert(action.acc_on);
    /* Confirmed two-mode contract: boot monitor emits an immediate logical
     * ACC-ON entry location even when the physical ACC input is low. */
    assert(work_mode_next_action(&action));
    assert(action.type == WORK_ACTION_REPORT_ENTRY);
    assert(action.acc_on);
    assert(!work_mode_next_action(&action));

    step(29U, false, false, 0U, true);
    assert(!work_mode_next_action(&action));
    step(30U, false, false, 0U, true);
    assert(work_mode_next_action(&action));
    assert(action.type == WORK_ACTION_REPORT_LOCATION);
    assert(action.acc_on);
    assert(!work_mode_next_action(&action));

    step(59U, false, false, 0U, true);
    assert(!work_mode_next_action(&action));
    step(60U, false, false, 0U, true);
    assert(work_mode_next_action(&action));
    assert(action.type == WORK_ACTION_REPORT_LOCATION);
    assert(action.acc_on);
}

static void test_boot_noise_does_not_restart_static_timer(void)
{
    work_mode_init(&DEFAULT_CONFIG, 0U, false);
    step(299U, false, false, 0U, true);
    step(300U, false, true, 0U, true);
    assert(work_mode_state() == WORK_MODE_STATIONARY_SLEEP);
    step(301U, false, false, 0U, true);
    assert(work_mode_state() == WORK_MODE_STATIONARY_SLEEP);
}

static void test_thirty_consecutive_200ms_hits_confirm_six_seconds(void)
{
    uint32_t i;
    work_mode_init(&DEFAULT_CONFIG, 0U, false);
    for (i = 1U; i <= 30U; ++i) {
        step_ms(i * 200U, false, true);
    }
    assert(work_mode_state() == WORK_MODE_BOOT_MONITOR);
    step_ms(31U * 200U, false, true);
    assert(work_mode_state() == WORK_MODE_REALTIME);
    assert(work_mode_logical_acc());
}

static void test_acc_falling_edge_precedes_same_step_vibration(void)
{
    work_mode_action_t actions[10];
    size_t count;
    uint32_t i;

    work_mode_init(&DEFAULT_CONFIG, 0U, true);
    (void)drain(actions, ARRAY_LEN(actions));
    step(1U, false, true, 0U, true);
    assert(work_mode_state() == WORK_MODE_STATIONARY_SLEEP);
    count = drain(actions, ARRAY_LEN(actions));
    assert(count >= 1U);
    assert(actions[0].type == WORK_ACTION_SET_LOGICAL_ACC);
    assert(!actions[0].acc_on);
    for (i = 0U; i < 30U; ++i) {
        step(2U + i, false, true, 0U, false);
    }
    assert(work_mode_state() == WORK_MODE_REALTIME);
}

static void test_stationary_deadlines_are_independent_and_simultaneous(void)
{
    static const work_mode_action_type_t expected[] = {
        WORK_ACTION_REPORT_LOCATION
    };
    enter_stationary(0U);
    step(179U, false, false, 0U, false);
    assert_actions((const work_mode_action_type_t[]){}, 0U);
    step(180U, false, false, 0U, false);
    assert_actions(expected, ARRAY_LEN(expected));
}

static void test_alarm_wakes_realtime_and_reports(void)
{
    work_mode_action_t action;
    enter_stationary(20U);
    step(21U, false, false, 0x00000005UL, false);
    assert(work_mode_state() == WORK_MODE_REALTIME);
    assert(work_mode_logical_acc());
    assert(work_mode_next_action(&action));
    /* Wake transition queues ON/GPS/entry actions before the alarm report. */
    bool saw_alarm = false;
    while (work_mode_next_action(&action)) {
        if (action.type == WORK_ACTION_REPORT_ALARM) {
            assert(action.alarm_bits == 0x00000005UL);
            saw_alarm = true;
        }
    }
    assert(saw_alarm);
}

static void test_deadlines_are_safe_across_uint32_wrap(void)
{
    static const work_mode_action_type_t expected[] = {
        WORK_ACTION_REPORT_LOCATION
    };
    enter_stationary(0xFFFFFFF0UL);
    step(0x000000A3UL, false, false, 0U, false);
    assert_actions((const work_mode_action_type_t[]){}, 0U);
    step(0x000000A4UL, false, false, 0U, false);
    assert_actions(expected, ARRAY_LEN(expected));
}

static void test_action_backlog_is_fixed_and_bounded(void)
{
    work_mode_action_t action;
    unsigned count = 0U;
    uint32_t i;
    enter_stationary(0U);
    for (i = 0U; i < 100U; ++i) {
        step(1U + i, false, false, 1UL << (i % 16U), false);
    }
    while (work_mode_next_action(&action)) {
        ++count;
        assert(count <= 8U);
    }
    assert(count > 0U);
}

static void test_full_queue_retries_complete_realtime_entry(void)
{
    static const work_mode_config_t fast_reports = {
        1U, 1U, 1U, 300U, 6U
    };
    work_mode_action_t actions[20];
    size_t count;
    size_t i;
    bool saw_acc_on = false;
    bool saw_gps_on = false;
    bool saw_realtime_entry = false;

    work_mode_init(&fast_reports, 0U, true);
    for (i = 1U; i <= 5U; ++i) {
        step((uint32_t)i, true, false, 0U, true);
    }
    step(6U, false, false, 0U, false);
    for (i = 7U; i <= 36U; ++i) {
        step((uint32_t)i, false, true, 0U, true);
    }
    count = drain(actions, ARRAY_LEN(actions));
    for (i = 0U; i < count; ++i) {
        if (actions[i].type == WORK_ACTION_SET_LOGICAL_ACC && actions[i].acc_on) {
            saw_acc_on = true;
        }
        if (actions[i].type == WORK_ACTION_GPS_ON) {
            saw_gps_on = true;
        }
        if (actions[i].type == WORK_ACTION_REPORT_ENTRY && actions[i].acc_on) {
            saw_realtime_entry = true;
        }
    }
    assert(work_mode_state() == WORK_MODE_REALTIME);
    assert(work_mode_logical_acc());
    assert(saw_acc_on && saw_gps_on && saw_realtime_entry);
}

static void test_full_queue_retries_complete_stationary_entry(void)
{
    static const work_mode_config_t fast_reports = {
        1U, 180U, 180U, 300U, 6U
    };
    work_mode_action_t actions[20];
    size_t count;
    size_t i;
    bool saw_acc_off = false;
    bool saw_sleep_entry = false;
    bool saw_gps_off = false;
    bool saw_stop1 = false;

    work_mode_init(&fast_reports, 0U, true);
    for (i = 1U; i <= 5U; ++i) {
        step((uint32_t)i, true, false, 0U, true);
    }

    step(6U, false, false, 0U, false);
    count = drain(actions, ARRAY_LEN(actions));
    for (i = 0U; i < count; ++i) {
        if (actions[i].type == WORK_ACTION_SET_LOGICAL_ACC && !actions[i].acc_on) {
            saw_acc_off = true;
        }
        if (actions[i].type == WORK_ACTION_REPORT_ENTRY && !actions[i].acc_on &&
            actions[i].historical_position) {
            saw_sleep_entry = true;
        }
        if (actions[i].type == WORK_ACTION_GPS_OFF) {
            saw_gps_off = true;
        }
        if (actions[i].type == WORK_ACTION_ENTER_STOP1) {
            saw_stop1 = true;
        }
    }
    assert(work_mode_state() == WORK_MODE_STATIONARY_SLEEP);
    assert(!work_mode_logical_acc());
    assert(saw_acc_off && saw_sleep_entry && saw_gps_off && saw_stop1);
}

static void test_full_queue_reversal_to_realtime_drops_stale_sleep_actions(void)
{
    static const work_mode_config_t fast_reports = {
        1U, 1U, 1U, 300U, 1U
    };
    work_mode_action_t actions[20];
    size_t count;
    size_t i;
    uint8_t essential_order = 0U;

    work_mode_init(&fast_reports, 0U, true);
    for (i = 1U; i <= 5U; ++i) {
        step((uint32_t)i, true, false, 0U, true);
    }
    step(6U, false, false, 0U, false);
    for (i = 7U; i <= 11U; ++i) {
        step((uint32_t)i, false, true, 0U, true);
    }

    count = drain(actions, ARRAY_LEN(actions));
    assert(work_mode_state() == WORK_MODE_REALTIME);
    assert(work_mode_logical_acc());
    for (i = 0U; i < count; ++i) {
        assert(!(actions[i].type == WORK_ACTION_SET_LOGICAL_ACC &&
                 !actions[i].acc_on));
        assert(!(actions[i].type == WORK_ACTION_REPORT_ENTRY &&
                 !actions[i].acc_on));
        assert(actions[i].type != WORK_ACTION_GPS_OFF);
        assert(actions[i].type != WORK_ACTION_ENTER_STOP1);
        if (essential_order == 0U &&
            actions[i].type == WORK_ACTION_SET_LOGICAL_ACC &&
            actions[i].acc_on) {
            essential_order = 1U;
        }
        if (essential_order == 1U &&
            actions[i].type == WORK_ACTION_GPS_ON) {
            essential_order = 2U;
        }
        if (essential_order == 2U &&
            actions[i].type == WORK_ACTION_REPORT_ENTRY &&
            actions[i].acc_on) {
            essential_order = 3U;
        }
    }
    assert(essential_order == 3U);
}

static void test_full_queue_reversal_to_stationary_preserves_sleep_payload(void)
{
    static const work_mode_config_t fast_reports = {
        1U, 180U, 180U, 300U, 1U
    };
    work_mode_action_t actions[20];
    size_t count;
    size_t i;
    uint8_t essential_order = 0U;

    work_mode_init(&fast_reports, 0U, false);
    for (i = 0U; i < 5U; ++i) {
        step((uint32_t)i, false, true, 0U, true);
    }
    for (i = 6U; i <= 10U; ++i) {
        step((uint32_t)i, true, false, 0U, true);
    }
    step(11U, false, false, 0U, false);

    count = drain(actions, ARRAY_LEN(actions));
    assert(work_mode_state() == WORK_MODE_STATIONARY_SLEEP);
    assert(!work_mode_logical_acc());
    for (i = 0U; i < count; ++i) {
        assert(!(actions[i].type == WORK_ACTION_SET_LOGICAL_ACC &&
                 actions[i].acc_on));
        assert(actions[i].type != WORK_ACTION_GPS_ON);
        assert(!(actions[i].type == WORK_ACTION_REPORT_ENTRY &&
                 actions[i].acc_on));
        if (essential_order == 0U &&
            actions[i].type == WORK_ACTION_SET_LOGICAL_ACC &&
            !actions[i].acc_on) {
            essential_order = 1U;
        }
        if (essential_order == 1U &&
            actions[i].type == WORK_ACTION_GPS_OFF) {
            essential_order = 2U;
        }
        if (essential_order == 2U &&
            actions[i].type == WORK_ACTION_REPORT_ENTRY &&
            !actions[i].acc_on &&
            actions[i].historical_position) {
            essential_order = 3U;
        }
        if (essential_order == 3U &&
            actions[i].type == WORK_ACTION_ENTER_STOP1) {
            essential_order = 4U;
        }
    }
    assert(essential_order == 4U);
}

static void test_unsafe_intervals_are_clamped_before_deadline_math(void)
{
    work_mode_config_t unsafe = DEFAULT_CONFIG;

    unsafe.stationary_timeout_s = UINT32_MAX;
    work_mode_init(&unsafe, 100U, false);
    step(100U, false, false, 0U, true);
    assert(work_mode_state() == WORK_MODE_BOOT_MONITOR);
    step(100U + 0x7FFFFFFFUL, false, false, 0U, true);
    assert(work_mode_state() == WORK_MODE_STATIONARY_SLEEP);
}

static void test_vibration_millisecond_conversion_does_not_wrap(void)
{
    work_mode_config_t unsafe = DEFAULT_CONFIG;
    uint32_t i;

    unsafe.stationary_timeout_s = 0x7FFFFFFFUL;
    unsafe.vibration_confirm_s = 4294968UL;
    work_mode_init(&unsafe, 0U, false);
    for (i = 0U; i < 4U; ++i) {
        step(i, false, true, 0U, false);
    }
    assert(work_mode_state() == WORK_MODE_BOOT_MONITOR);
}

static void test_realtime_without_acc_enters_sleep_after_static_timeout(void)
{
    uint32_t i;

    work_mode_init(&DEFAULT_CONFIG, 0U, false);
    for (i = 0U; i < 30U; ++i) {
        step(i, false, true, 0U, true);
    }
    assert(work_mode_state() == WORK_MODE_REALTIME);
    step(328U, false, false, 0U, true);
    assert(work_mode_state() == WORK_MODE_REALTIME);
    step(329U, false, false, 0U, true);
    assert(work_mode_state() == WORK_MODE_STATIONARY_SLEEP);
}

static void test_stationary_acc_high_reenters_realtime(void)
{
    work_mode_action_t actions[8];
    size_t count;
    size_t i;
    bool saw_acc_on = false;
    bool saw_realtime_entry = false;

    enter_stationary(0U);
    step(1U, true, false, 0U, true);
    assert(work_mode_state() == WORK_MODE_REALTIME);
    count = drain(actions, ARRAY_LEN(actions));
    for (i = 0U; i < count; ++i) {
        if (actions[i].type == WORK_ACTION_SET_LOGICAL_ACC && actions[i].acc_on)
            saw_acc_on = true;
        if (actions[i].type == WORK_ACTION_REPORT_ENTRY && actions[i].acc_on)
            saw_realtime_entry = true;
    }
    assert(saw_acc_on);
    assert(saw_realtime_entry);
    step(2U, false, false, 0U, false);
    assert(work_mode_state() == WORK_MODE_STATIONARY_SLEEP);
}

int main(void)
{
    test_pa12_high_boot_enters_realtime_once();
    test_pa12_low_to_high_enters_realtime_and_sets_acc_on();
    test_pa12_low_without_vibration_sleeps_after_five_minutes();
    test_boot_monitor_waits_indefinitely_without_gps_fix();
    test_boot_monitor_reports_acc_on_every_moving_interval();
    test_boot_noise_does_not_restart_static_timer();
    test_thirty_consecutive_200ms_hits_confirm_six_seconds();
    test_acc_falling_edge_precedes_same_step_vibration();
    test_stationary_deadlines_are_independent_and_simultaneous();
    test_alarm_wakes_realtime_and_reports();
    test_deadlines_are_safe_across_uint32_wrap();
    test_action_backlog_is_fixed_and_bounded();
    test_full_queue_retries_complete_realtime_entry();
    test_full_queue_retries_complete_stationary_entry();
    test_full_queue_reversal_to_realtime_drops_stale_sleep_actions();
    test_full_queue_reversal_to_stationary_preserves_sleep_payload();
    test_unsafe_intervals_are_clamped_before_deadline_math();
    test_vibration_millisecond_conversion_does_not_wrap();
    test_realtime_without_acc_enters_sleep_after_static_timeout();
    test_stationary_acc_high_reenters_realtime();
    return 0;
}
'''


def compiler() -> str:
    found = os.environ.get("CC") or shutil.which("gcc") or shutil.which("cc")
    if not found:
        raise AssertionError("host C compiler is required for work-mode policy test")
    return found


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="work_mode_policy_") as directory:
        temp = Path(directory)
        harness = temp / "work_mode_policy_harness.c"
        executable = temp / "work_mode_policy_harness.exe"
        harness.write_text(HARNESS, encoding="ascii")
        command = [
            compiler(), "-std=c99", "-Wall", "-Wextra", "-Werror",
            "-I", str(ROOT / "include"), str(harness),
            str(ROOT / "src" / "work_mode.c"), "-o", str(executable),
        ]
        built = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        if built.returncode:
            raise AssertionError("work-mode policy host build failed:\n" + built.stderr)
        run = subprocess.run([str(executable)], cwd=ROOT, capture_output=True, text=True)
        if run.returncode:
            raise AssertionError("work-mode policy host test failed:\n" + run.stderr)
    print("work-mode policy: PASS")


if __name__ == "__main__":
    main()
