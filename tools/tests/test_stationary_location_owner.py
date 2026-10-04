#!/usr/bin/env python3
"""Regression contract for the stationary work-mode report owner.

The work-mode state machine owns every stationary 0x0200: one entry report
and any configured retained-position cadence.  The legacy JT808 live-GNSS
timer must not run concurrently while GNSS is off, otherwise it repeatedly
falls back to the same old fix.
"""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "src" / "jt808.c").read_text(encoding="utf-8")


def function_body(name: str) -> str:
    match = re.search(rf"\b{name}\s*\([^;]*?\)\s*\{{", SOURCE, re.S)
    assert match, f"missing function: {name}"
    start = match.end() - 1
    depth = 0
    for index in range(start, len(SOURCE)):
        if SOURCE[index] == "{":
            depth += 1
        elif SOURCE[index] == "}":
            depth -= 1
            if depth == 0:
                return SOURCE[start + 1:index]
    raise AssertionError(f"unterminated function: {name}")


def test_stationary_work_mode_disables_legacy_location_timer():
    """A stationary sleep episode cannot send a live-timer 0x0200."""
    assert '#include "work_mode.h"' in SOURCE
    timer = function_body("process_location_timer")
    guard = re.search(
        r"if\s*\(\s*work_mode_state\s*\(\s*\)\s*==\s*"
        r"WORK_MODE_STATIONARY_SLEEP\s*\)\s*\{[\s\S]*?"
        r"send_pending_live_locations\s*\(\s*&first_snapshot\s*,\s*now\s*,\s*false\s*\)"
        r"[\s\S]*?return\s*;\s*\}",
        timer,
    )
    assert guard, (
        "legacy JT808 location timer must return during stationary sleep; "
        "work_mode.c owns retained-position reports"
    )


def test_work_mode_report_synchronizes_legacy_location_timer():
    """A work-mode 0200 cannot leave the legacy timer immediately due."""
    wrapper = function_body("jt808_send_location_work_mode")
    assert re.search(
        r"result\s*=\s*send_frame_broadcast\s*\(\s*&frame\s*\)\s*;"
        r"[\s\S]*?result\s*==\s*0[\s\S]*?s_last_location_ms\s*=\s*TICK_MS\s*\(\s*\)",
        wrapper,
    ), "successful work-mode 0200 must synchronize the shared location timer"


if __name__ == "__main__":
    test_stationary_work_mode_disables_legacy_location_timer()
    test_work_mode_report_synchronizes_legacy_location_timer()
    print("test_stationary_location_owner: PASS")
