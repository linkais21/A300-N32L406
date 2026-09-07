#!/usr/bin/env python3
"""Contracts for the three PA12-bounce hardening fixes.

Field capture ReceivedTofile-COM4-2026_9_7_14-18-24.TXT logged 191 ACC edges
and 21 mode transitions in one session, several times flipping twice inside the
same second. Three distinct defects fell out of that bounce:

1. Alternating ACC ON/OFF reports reached the platform, which kept whichever
   edge arrived last: ACC ON at 14:41:18 did not settle until 14:42:07.
2. The STOP1 wake filter re-read PA12 when deciding whether an ACC wake was
   real, so mid-bounce it could read the opposite level and discard a genuine
   ACC-ON wake. The capture logged "ACC-off edge ignored as wake" on a pass
   that simultaneously reported pin_high=0 acc_on=1.
3. The retained snapshot's clock ran backwards (06:41:17 -> 06:41:06) because
   repeated sleep entries re-captured a live fix whose own timestamp was older
   than the value gps_advance_last_trusted_seconds() had already advanced to.

Source contracts rather than a compiled harness: all three live in modules that
need the DMA/UART/SDK environment to link. What must not silently regress is
the wiring.
"""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "src" / "main.c").read_text(encoding="utf-8")
SLEEP = (ROOT / "src" / "work_mode_sleep.c").read_text(encoding="utf-8")
GPS = (ROOT / "src" / "gps.c").read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def function_body(source: str, name: str) -> str:
    match = re.search(rf"\b{name}\s*\([^;]*?\)\s*\{{", source, re.S)
    require(match is not None, f"missing function body: {name}")
    start = match.end() - 1
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start + 1:index]
    raise AssertionError(f"unterminated function body: {name}")


def check_report_debounce() -> None:
    require("ACC_REPORT_SETTLE_S" in MAIN,
            "no settle window for ACC state-change reports")
    window = re.search(r"#define\s+ACC_REPORT_SETTLE_S\s+(\d+)U?", MAIN)
    require(window is not None, "settle window is not a plain constant")
    seconds = int(window.group(1))
    require(1 <= seconds <= 30,
            f"settle window {seconds}s is outside a sane 1..30 range")

    suppress = function_body(MAIN, "acc_report_suppressed")
    # The first edge must always go out: that is what keeps a real ACC change
    # reported within a second.
    require(re.search(r"!s_acc_report_valid[\s\S]{0,300}?return\s+false",
                      suppress) is not None,
            "the first ACC report is not sent immediately")
    # A reversal inside the window is deferred, not dropped.
    require("s_acc_report_deferred = true" in suppress,
            "a reversal inside the window is not recorded for later")
    require("ACC_REPORT_SETTLE_S" in suppress,
            "the suppression decision does not consult the settle window")

    settle = function_body(MAIN, "acc_report_settle")
    require("s_acc_report_deferred" in settle,
            "the settle path does not consume the deferred flag")
    require("hw_acc_is_on()" in settle,
            "the settle path does not confirm the pin actually stayed put")
    require("jt808_send_location_work_mode" in settle,
            "a deferred ACC level is never actually reported")
    # Losing a deferred change would be worse than the bounce it filters.
    caller = function_body(MAIN, "work_mode_process")
    require("acc_report_settle(" in caller,
            "the settle path is never called, so deferred levels are lost")

    # Timing must survive STOP1: TICK_MS() is suspended while asleep.
    require(not re.search(r"s_acc_report_s\s*=\s*TICK_MS", MAIN),
            "ACC report timing must not use the sleep-suspended tick")


def check_wake_filter_race() -> None:
    isr = function_body(SLEEP, "work_mode_sleep_isr_wake")
    require("s_acc_on_at_wake" in isr,
            "the ACC level is not captured when the wake is raised")
    require("hw_acc_is_on()" in isr,
            "the ISR does not sample the pin at edge time")

    # The filter must use the latched level, never a fresh read.
    filter_line = re.search(
        r"if\s*\(\s*\(\s*s_wake\s*&\s*WORK_SLEEP_WAKE_ACC\s*\)\s*!=\s*0U\s*&&"
        r"\s*(![A-Za-z_][A-Za-z0-9_]*(?:\(\))?)\s*\)", SLEEP)
    require(filter_line is not None, "the ACC wake filter is missing")
    require(filter_line.group(1) == "!s_acc_on_at_wake",
            "the wake filter still re-reads the pin instead of the latched "
            f"level (found {filter_line.group(1)})")


def check_retained_clock_monotonic() -> None:
    require("retained_clock_is_newer" in GPS,
            "no monotonicity guard on the retained clock")
    capture = function_body(GPS, "gps_capture_last_trusted")
    require("retained_clock_is_newer" in capture,
            "the capture path does not check clock monotonicity")
    # The guard must only refuse an older clock, and only when a snapshot
    # already exists -- otherwise the very first capture could never happen.
    require(re.search(r"s_last_trusted_valid\s*&&[\s\S]{0,120}?"
                      r"!retained_clock_is_newer", capture) is not None,
            "the guard must not block the first capture")

    helper = function_body(GPS, "retained_clock_is_newer")
    for field in ("year", "month", "day", "hour", "minute", "second"):
        require(field in helper,
                f"the clock comparison ignores the {field} field")
    require("s_last_trusted." in helper,
            "the comparison does not read the retained snapshot")


def check_acc_wake_hold() -> None:
    """An ACC wake must keep the CPU awake until the PA12 debounce commits.

    A field capture (ReceivedTofile-COM4-2026_9_7_15-47-18.TXT) showed the wake
    and the ACC edge both recorded correctly, then "[STOP1] enter" on the same
    pass, and the mode transition only after the next 15 s RTC slice -- ACC ON
    took 22..45 s to reach the platform. Vibration wakes already had such a
    hold; ACC wakes had none.
    """
    require("ACC_WAKE_HOLD_MS" in MAIN,
            "no hold window for ACC wakes")
    window = re.search(r"#define\s+ACC_WAKE_HOLD_MS\s+(\d+)U?", MAIN)
    require(window is not None, "ACC hold window is not a plain constant")
    hold_ms = int(window.group(1))
    # Must outlast the 50 ms debounce it protects, and stay bounded so a pin
    # that never settles cannot hold sleep off indefinitely.
    require(50 < hold_ms <= 2000,
            f"ACC hold {hold_ms}ms must exceed the 50ms debounce and stay bounded")

    body = function_body(MAIN, "work_mode_process")
    require(re.search(r"wake\s*&\s*WORK_SLEEP_WAKE_ACC[\s\S]*?"
                      r"acc_wake_window\s*=\s*true", body) is not None,
            "an ACC wake does not arm the hold window")
    require("ACC_WAKE_HOLD_MS" in body,
            "the hold decision does not consult the window")
    # The STOP1 re-entry at the end of the loop is the thing being gated.
    require(re.search(r"WORK_MODE_STATIONARY_SLEEP[\s\S]{0,300}?"
                      r"!acc_wake_hold[\s\S]{0,300}?work_mode_sleep_process",
                      body) is not None,
            "STOP1 re-entry is not gated on the ACC hold")
    # Reaching REALTIME means the debounce committed: the hold must release.
    require(re.search(r"WORK_MODE_REALTIME\s*\|\|\s*!acc_wake_hold[\s\S]{0,160}?"
                      r"acc_wake_window\s*=\s*false", body) is not None,
            "the ACC hold is not released once the transition happened")


def main() -> None:
    check_report_debounce()
    check_wake_filter_race()
    check_retained_clock_monotonic()
    check_acc_wake_hold()
    print("test_acc_bounce_hardening: PASS")


if __name__ == "__main__":
    main()