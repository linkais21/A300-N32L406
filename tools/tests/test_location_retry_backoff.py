#!/usr/bin/env python3
"""Contract: a missing position must not be retried in a tight loop.

Field capture ReceivedTofile-COM4-2026_9_7_12-26-30.TXT: 1092 of the log's
1131 lines were the same "0200 drop reason=no-fix-no-trusted" line, with zero
successful reports and almost nothing else. At boot GNSS has no fix and no
trusted snapshot has ever been captured, so the report failed, main.c re-queued
it immediately, and it failed again at once. The blocking debug UART then
starved the very loop that would have acquired the fix.

The repaired contract sends a zero-coordinate unfixed snapshot when no trusted
fix exists. A failed transport/storage attempt still yields the dispatcher,
so retry cannot spin within the same pass. Runtime encoding and storage are
covered by test_jt808_dual_session and test_jt808_nofix_clock.
"""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
HEADER = (ROOT / "include" / "jt808.h").read_text(encoding="utf-8")
JT808 = (ROOT / "src" / "jt808.c").read_text(encoding="utf-8")
MAIN = (ROOT / "src" / "main.c").read_text(encoding="utf-8")


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


def main() -> None:
    sender = function_body(JT808, "send_location_work_mode")
    require(sender.count("gps_get_unfixed_report(&snapshot)") == 2,
            "historical and live missing-fix paths must still produce a report")
    require("return JT808_SEND_NO_POSITION" not in sender,
            "missing GNSS must not discard the work-mode report")
    require("blind_zone_append" in sender and "return -2;" in sender,
            "unconfirmed main delivery must retain a retryable storage path")
    require("drop reason=" not in sender,
            "missing-fix drop logging has returned")

    # The dispatcher must yield after a failed attempt.
    caller = function_body(MAIN, "work_mode_process")
    # A transport failure must still be retried, or reports would be lost.
    require("work_mode_retry_action" in caller,
            "transport failures are no longer retried at all")
    require(re.search(
        r"sent\s*!=\s*0[\s\S]{0,180}?work_mode_retry_action\s*\(\s*&action\s*\)"
        r"[\s\S]{0,100}?processed\s*=\s*8U",
        caller) is not None,
        "a failed location can be retried repeatedly in one dispatcher pass")

    print("test_location_retry_backoff: PASS")


if __name__ == "__main__":
    main()
