#!/usr/bin/env python3
"""Contract: a missing position must not be retried in a tight loop.

Field capture ReceivedTofile-COM4-2026_9_7_12-26-30.TXT: 1092 of the log's
1131 lines were the same "0200 drop reason=no-fix-no-trusted" line, with zero
successful reports and almost nothing else. At boot GNSS has no fix and no
trusted snapshot has ever been captured, so the report failed, main.c re-queued
it immediately, and it failed again at once. The blocking debug UART then
starved the very loop that would have acquired the fix.

Two independent guards are pinned here, because either one alone still leaves a
hot loop or a silent one:
  1. the sender reports "no position yet" distinctly from a transport failure,
     and rate-limits the notice;
  2. the caller does not re-queue that specific outcome.
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
    # 1. A distinct, non-zero, negative result for "no position available".
    require("JT808_SEND_NO_POSITION" in HEADER,
            "no distinct result for the no-position case")
    value = re.search(r"#define\s+JT808_SEND_NO_POSITION\s*\(?\s*(-\d+)\s*\)?",
                      HEADER)
    require(value is not None, "JT808_SEND_NO_POSITION is not a plain constant")
    require(int(value.group(1)) < 0,
            "JT808_SEND_NO_POSITION must stay negative: callers test for failure")

    sender = function_body(JT808, "jt808_send_location_work_mode")
    require(sender.count("JT808_SEND_NO_POSITION") >= 2,
            "both no-position paths (historical and live) must use the "
            "distinct result")
    # The distinct result must not leak into transport failures, or the caller
    # would stop retrying a genuinely retryable send.
    require("return -1;" in sender,
            "transport failures must stay distinguishable from no-position")

    # 2. The notice is rate-limited rather than printed on every attempt.
    require("log_location_unavailable" in JT808,
            "the no-position notice is not funnelled through a limiter")
    limiter = function_body(JT808, "log_location_unavailable")
    require("JT808_LOCATION_DROP_LOG_MS" in limiter,
            "the limiter does not use a minimum log interval")
    require("suppressed" in limiter,
            "the limiter hides how many notices it dropped")
    interval = re.search(r"#define\s+JT808_LOCATION_DROP_LOG_MS\s+(\d+)U?",
                         HEADER)
    require(interval is not None, "log interval is not a plain constant")
    require(int(interval.group(1)) >= 1000,
            "a sub-second log interval defeats the rate limit")
    # The direct print must be gone from the sender's no-position paths.
    require("drop reason=" not in sender,
            "the sender still prints the drop directly, bypassing the limiter")

    # 3. The caller must not re-queue the no-position outcome.
    caller = function_body(MAIN, "work_mode_process")
    require("JT808_SEND_NO_POSITION" in caller,
            "the action dispatcher ignores the no-position result")
    require(re.search(
        r"jt808_send_location_work_mode[\s\S]*?"
        r"!=\s*JT808_SEND_NO_POSITION[\s\S]{0,200}?work_mode_retry_action",
        caller) is not None,
        "a no-position result is still re-queued immediately")
    # A transport failure must still be retried, or reports would be lost.
    require("work_mode_retry_action" in caller,
            "transport failures are no longer retried at all")

    print("test_location_retry_backoff: PASS")


if __name__ == "__main__":
    main()