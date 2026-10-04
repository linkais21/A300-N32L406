#!/usr/bin/env python3
"""Contract checks for bounded JT808 frame-build failure handling.

AUTH and REGISTER frame allocation/header failures happen before the common
finish/send path.  They must still consume the session retry budget, otherwise
the main loop immediately retries 0x0102 forever without entering backoff.
"""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "src/jt808.c").read_text(encoding="utf-8")


def body(name: str) -> str:
    match = re.search(rf"\b{name}\s*\([^;]*?\)\s*\{{", SOURCE, re.S)
    if match is None:
        raise AssertionError(f"missing function body: {name}")
    start = match.end() - 1
    depth = 0
    for index in range(start, len(SOURCE)):
        if SOURCE[index] == "{":
            depth += 1
        elif SOURCE[index] == "}":
            depth -= 1
            if depth == 0:
                return SOURCE[start + 1:index]
    raise AssertionError(f"unterminated function body: {name}")


def branch_body(source: str, marker: str) -> str:
    """Return the braced body of the first `if (marker)` branch."""
    match = re.search(rf"if\s*\(\s*!\s*{marker}\s*\)\s*\{{", source)
    if match is None:
        raise AssertionError(f"missing failure branch: {marker}")
    start = match.end() - 1
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start + 1:index]
    raise AssertionError(f"unterminated failure branch: {marker}")


def require_failure_budget(function: str, action: str) -> None:
    source = body(function)
    for marker in ("frame_init\\s*\\(\\s*&f\\s*\\)",
                   "build_header\\s*\\(\\s*&f\\s*,[^)]*\\)"):
        branch = branch_body(source, marker)
        mark = branch.find("jt808_session_mark_send_failed")
        ret = branch.find("return -1")
        if mark < 0:
            raise AssertionError(f"{function}: {marker} does not consume retry budget")
        if ret < 0 or mark > ret:
            raise AssertionError(
                f"{function}: {marker} returns before mark_send_failed ({action})")
        if action not in branch[mark:ret]:
            raise AssertionError(f"{function}: wrong retry action in {marker}")


require_failure_budget("send_register_current_identity", "JT808_ACTION_REGISTER")
require_failure_budget("jt808_send_auth_to", "JT808_ACTION_AUTH")

# STOP1 suspends SysTick while RTC service windows continue to run.  Heartbeat
# scheduling must therefore use the sleep-aware monotonic seconds source and
# advance the last-send marker only after a successful frame send.  This
# contract protects the 180 s default cadence from regressing to a frozen
# TICK_MS() clock or duplicate retries on a failed send.
if "work_mode_sleep_monotonic_s" not in SOURCE:
    raise AssertionError("JT808 heartbeat lacks STOP1 monotonic clock")
if "HEARTBEAT_DEFAULT_S" not in SOURCE:
    raise AssertionError("JT808 heartbeat default is not wired to configuration")
if not re.search(r"now_s\s*=\s*jt808_monotonic_s\s*\(\s*\)", SOURCE):
    raise AssertionError("JT808 process does not sample monotonic seconds")
if not re.search(r"now_s\s*-\s*s_last_heartbeat_s", SOURCE):
    raise AssertionError("heartbeat cadence is not evaluated in seconds")
if not re.search(r"s_cfg\.heartbeat_s", SOURCE):
    raise AssertionError("heartbeat configuration is not used")
if not re.search(r"if\s*\(\s*jt808_send_heartbeat\(\)\s*==\s*0\s*\)\s*s_last_heartbeat_s\s*=\s*now_s", SOURCE):
    raise AssertionError("heartbeat marker advances before successful send")
print("test_jt808_send_failure_contract: PASS")
