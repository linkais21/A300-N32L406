#!/usr/bin/env python3
"""Contract for the shallow-sleep profile (A300_STOP1_SLEEP=0, the default).

The A300/N32G452 standard profile does not enter STOP1: it parks in a shallow
WFI with SysTick still running, so the main loop re-polls PA12 every 1 ms and
the 50 ms ACC debounce advances on real time.  ACC detection therefore does not
depend on the EXTI edge surviving the sleep entry.

test_acc_stop1_contract.py and test_acc_bounce_hardening.py both assert the
STOP1 wiring, which still exists behind `#if A300_STOP1_SLEEP`.  Because those
are source-text checks they pass regardless of which profile is selected, so
they do NOT cover this one.  That is what this file is for.
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from test_tcp_manager_fip import compiler

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "src" / "main.c").read_text(encoding="utf-8", errors="replace")
SLEEP_C = (ROOT / "src" / "work_mode_sleep.c").read_text(encoding="utf-8", errors="replace")
SLEEP_H = (ROOT / "include" / "work_mode_sleep.h").read_text(encoding="utf-8", errors="replace")

failures = []


def require(condition: bool, message: str) -> None:
    if not condition:
        failures.append(message)


def function_body(source: str, name: str) -> str:
    start = source.find(f"\n{name}(")
    if start < 0:
        start = source.find(f" {name}(")
    if start < 0:
        raise AssertionError(f"function not found: {name}")
    brace = source.find("{", start)
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[brace:index + 1]
    raise AssertionError(f"unterminated function: {name}")


def check_profile_switch() -> None:
    """The profile must be a build-time switch defaulting to shallow."""
    require(re.search(r"#ifndef\s+A300_STOP1_SLEEP\s*\n\s*#define\s+A300_STOP1_SLEEP\s+0",
                      MAIN) is not None,
            "A300_STOP1_SLEEP must default to 0 (shallow profile)")
    # STOP1 must remain reachable so the deep-sleep profile stays revertible.
    require("#if A300_STOP1_SLEEP" in MAIN,
            "the STOP1 path must remain selectable, not deleted")
    require("work_mode_sleep_process(15000U, wake)" in MAIN,
            "the STOP1 profile must still call the deep-sleep service")


def check_shallow_entry_exists() -> None:
    require("void work_mode_sleep_shallow(void);" in SLEEP_H,
            "work_mode_sleep_shallow is not declared")
    body = function_body(SLEEP_C, "void work_mode_sleep_shallow")
    require("PWR_EnterSLEEPMode" in body,
            "the shallow window must use SLEEP/WFI, not a STOP state")
    require("PWR_EnterStopState" not in body and "PWR_EnterSTOP2Mode" not in body,
            "the shallow window must not enter any STOP mode")
    # SysTick keeping time is the whole point: suspending it would freeze
    # TICK_MS() and stall the 50 ms debounce exactly as STOP1 did.
    require("stop1_suspend_periodic_irqs" not in body,
            "the shallow window must not suspend SysTick/TIM8")
    require("stop1_suspend_modem_io" not in body,
            "the shallow window must leave the modem UART/DMA running")
    require("IWDG_ReloadKey" in body,
            "the shallow window must service the watchdog across WFI")


def check_modem_stays_awake() -> None:
    """A downlink (0x8103 and friends) must be serviced on the next loop pass.

    Putting the modem into QSCLK here would reintroduce the slice-boundary
    latency the shallow profile exists to remove, and would cost two AT
    round-trips plus a 50 ms delay on every tick.
    """
    body = function_body(SLEEP_C, "void work_mode_sleep_shallow")
    require("ec800m_sleep_enable" not in body,
            "the shallow window must not put the modem into QSCLK sleep")


def check_ota_blocks_shallow_entry() -> None:
    """Compile the unchanged production entry and OTA predicate with HW spies.

    Removing the entry guard must expose a WFI/QSCLK operation in every active
    OTA state. Keep the watchdog and pending wake evidence observable as well.
    """
    cc = compiler()
    if cc is None:
        raise AssertionError("OTA shallow-entry behavior requires a C compiler")
    tcp_source = (ROOT / "src" / "tcp_manager.c").read_text(encoding="utf-8")
    harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include "fota.h"
static bool s_ready, s_stop1_log_active;
static uint32_t s_stop1_slice_count, s_wake;
static unsigned watchdogs, sleeps, alarms, modem_wakes;
static fota_state_t ota_state;
#define PWR_STOPENTRY_WFI 1U
fota_state_t fota_get_state(void) { return ota_state; }
static void rtc_alarm_clear(void) { ++alarms; }
static void ec800m_sleep_disable(void) { ++modem_wakes; }
static void IWDG_ReloadKey(void) { ++watchdogs; }
static void __DSB(void) { }
static void PWR_EnterSLEEPMode(uint32_t regulator, uint8_t entry) {
    assert(regulator == 0U && entry == PWR_STOPENTRY_WFI);
    ++sleeps;
}
#define dbg_printf(...) ((void)0)
'''
    harness += "\nbool tcp_manager_ota_active(void)\n" + function_body(
        tcp_source, "bool tcp_manager_ota_active")
    harness += "\nvoid work_mode_sleep_shallow(void)\n" + function_body(
        SLEEP_C, "void work_mode_sleep_shallow")
    harness += r'''
int main(void) {
    static const fota_state_t active[] = {
        FOTA_STATE_CHECK_CONNECTING, FOTA_STATE_CHECKING,
        FOTA_STATE_PREPARING, FOTA_STATE_CONNECTING,
        FOTA_STATE_DOWNLOADING, FOTA_STATE_VERIFYING, FOTA_STATE_READY
    };
    s_ready = false;
    work_mode_sleep_shallow();
    assert(!sleeps && !alarms && !modem_wakes);
    s_ready = true;
    for (unsigned i = 0U; i < sizeof active / sizeof active[0]; ++i) {
        ota_state = active[i];
        watchdogs = sleeps = alarms = modem_wakes = 0U;
        s_stop1_log_active = true;
        s_stop1_slice_count = 3U;
        s_wake = 0x05U;
        work_mode_sleep_shallow();
        assert(sleeps == 0U && alarms == 0U && modem_wakes == 0U);
        assert(watchdogs >= 1U);
        assert(s_stop1_log_active && s_stop1_slice_count == 3U);
        assert(s_wake == 0x05U);
        /* Both normal completion and error release the sleep prohibition. */
        ota_state = i % 2U ? FOTA_STATE_IDLE : FOTA_STATE_ERROR;
        work_mode_sleep_shallow();
        assert(sleeps == 1U && alarms == 1U && modem_wakes == 1U);
        assert(watchdogs >= 3U);
        assert(!s_stop1_log_active && s_stop1_slice_count == 0U);
        assert(s_wake == 0x05U);
        work_mode_sleep_shallow();
        assert(sleeps == 2U && alarms == 1U && modem_wakes == 1U);
    }
    return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix="ota_shallow_host_") as directory:
        temp = Path(directory)
        source = temp / "harness.c"
        binary = temp / "harness.exe"
        source.write_text(harness, encoding="utf-8")
        subprocess.run([cc, "-std=c99", "-Wall", "-Wextra", "-Werror",
                        "-I", str(ROOT / "include"), str(source),
                        "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)


def check_tail_placement_and_gate() -> None:
    """The WFI belongs at the loop tail, gated by the same holds STOP1 used."""
    process = function_body(MAIN, "void work_mode_process")
    require(re.search(r"WORK_MODE_STATIONARY_SLEEP[\s\S]{0,300}?"
                      r"!vibration_wake_hold[\s\S]{0,300}?"
                      r"!acc_wake_hold[\s\S]{0,300}?"
                      r"s_shallow_sleep_allowed\s*=\s*true", process) is not None,
            "the shallow gate must require STATIONARY_SLEEP and no wake hold")
    # work_mode_process() runs mid-loop; sleeping there would delay every
    # _process() after it, so the decision is published and consumed later.
    require("work_mode_sleep_shallow()" not in process,
            "the shallow WFI must not run inside work_mode_process")
    main_body = function_body(MAIN, "int main")
    last_phase = function_body(MAIN, "static void service_after_commands")
    require("service_after_commands()" in main_body and
            "idle_sleep_process()" in last_phase,
            "the shallow WFI helper must run in the last main-loop phase")
    phase_tail = last_phase[last_phase.rfind("idle_sleep_process()") +
                            len("idle_sleep_process()"):]
    main_tail = main_body[main_body.rfind("service_after_commands()") +
                          len("service_after_commands()"):]
    require(re.search(r"_process\s*\(", phase_tail + main_tail) is None,
            "the shallow WFI must be the last thing in the loop, after every "
            "_process() has had its pass")


def check_retained_timestamp_tracks_shallow_sleep() -> None:
    """Historical 0x0200 time must advance while GNSS is powered down."""
    # The production GPS clock now covers awake and shallow WFI equally.
    # Runtime rollover/no-fix coverage lives in test_gps_retained_clock.py.
    gps = (ROOT / "src/gps.c").read_text(encoding="utf-8")
    for signature in ("void gps_process", "bool gps_get_last_trusted"):
        require("retained_clock_advance_awake()" in function_body(gps, signature),
                "GPS processing and retained reads must account running SysTick")
    require("gps_advance_last_trusted_seconds" not in MAIN,
            "main must not add shallow time again after GPS clock accounting")
    require("gps_advance_last_trusted_seconds(elapsed_seconds)" in SLEEP_C,
            "STOP1 must still account time while SysTick is stopped")


def main() -> None:
    check_profile_switch()
    check_shallow_entry_exists()
    check_modem_stays_awake()
    check_tail_placement_and_gate()
    check_retained_timestamp_tracks_shallow_sleep()
    check_ota_blocks_shallow_entry()
    if failures:
        for message in failures:
            print(f"FAIL: {message}", file=sys.stderr)
        raise SystemExit(1)
    print("test_shallow_sleep_contract: PASS")


if __name__ == "__main__":
    main()
