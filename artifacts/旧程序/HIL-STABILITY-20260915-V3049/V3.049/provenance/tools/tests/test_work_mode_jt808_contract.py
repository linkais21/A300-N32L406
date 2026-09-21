#!/usr/bin/env python3
"""Source contract for work-mode JT808 location-report hooks."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
HEADER = (ROOT / "include/jt808.h").read_text(encoding="utf-8")
SOURCE = (ROOT / "src/jt808.c").read_text(encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def function_body(name: str) -> str:
    match = re.search(rf"\b{name}\s*\([^;]*?\)\s*\{{", SOURCE, re.S)
    require(match is not None, f"missing function body: {name}")
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


# Public hooks are consumed by work_mode.c; changing these declarations breaks
# that integration boundary.
require("void jt808_set_logical_acc(bool on);" in HEADER,
        "missing logical ACC setter declaration")
require("bool jt808_get_logical_acc(void);" in HEADER,
        "missing logical ACC getter declaration")
require(re.search(
    r"int\s+jt808_send_location_work_mode\s*\(\s*uint32_t\s+alarm_bits\s*,"
    r"\s*bool\s+historical_position\s*\)\s*;", HEADER) is not None,
    "missing work-mode location declaration")

# Before the first work-mode override, the getter must retain the established
# physical PA12 behavior. Once overridden, online location status must consume
# the logical value rather than reading PA12 directly.
getter = function_body("jt808_get_logical_acc")
require("hw_acc_is_on()" in getter,
        "logical ACC getter lost the default physical PA12 fallback")
require("s_logical_acc_override_set" in getter,
        "logical ACC getter does not distinguish unset from overridden state")

compact = function_body("encode_location_compact")
require("hw_acc_is_on()" in compact,
        "blind-zone compact serialization must retain physical ACC behavior")
require("jt808_get_logical_acc" not in compact,
        "logical ACC override must not change blind-zone compact serialization")

online = function_body("encode_location_online")
require("jt808_get_logical_acc()" in online,
        "complete online location status does not use logical ACC")
require("alarm_bits" in online and
        re.search(r"body\s*\[\s*0\s*\].*alarm_bits", online) is not None,
        "caller alarm bits do not flow into the online 0x0200 body")
require("LOC_FLAG_BEIDOU_FIXED" in HEADER,
        "JT808 status contract does not define BeiDou positioning bit19")
require(re.search(
    r"historical_position[\s\S]*~\s*LOC_FLAG_GPS_FIXED", online) is not None,
    "historical reports do not clear the current-fix status bit")
require(re.search(
    r"historical_position[\s\S]*~\s*\([^;]*LOC_FLAG_BEIDOU_FIXED", online)
    is None,
    "historical reports must preserve the trusted BeiDou source bit")

# The work-mode wrapper must keep the existing complete online extension path;
# it may not fall back to the compact blind-zone payload.
wrapper = function_body("jt808_send_location_work_mode")
require(re.search(
    r"encode_location_online\s*\(\s*&snapshot\s*,\s*body\s*,\s*alarm_bits\s*,"
    r"\s*historical_position\s*\)", wrapper) is not None,
    "work-mode report bypasses the complete online builder")
require("JT808_LOCATION_ONLINE_MAX" in wrapper,
        "work-mode report buffer does not cover the complete extension profile")
require("MSG_LOCATION_REPORT" in wrapper,
        "work-mode wrapper does not build a 0x0200 location report")

# A live-fix report must not be dropped when GNSS has not re-acquired yet.
# GNSS is powered down in STOP1, so on wake the live object is stale for as
# long as the receiver takes to get a fix; dropping the frame there lost ACC
# state changes and the whole stationary reporting cadence. Fall back to the
# retained fix and mark the report historical instead.
require("gps_get_last_trusted" in wrapper,
        "work-mode report has no retained-fix fallback")
require(re.search(
    r"jt808_location_snapshot_valid[\s\S]*?gps_get_last_trusted"
    r"[\s\S]{0,300}?historical_position\s*=\s*true", wrapper) is not None,
    "a stale live fix does not fall back to the retained fix")
require(wrapper.count("gps_get_last_trusted") >= 2,
        "retained-fix fallback must cover both the historical and live paths")
# The fallback must still refuse to invent a position when nothing was ever
# captured, and must say why rather than failing silently.
require("no-fix-no-trusted" in wrapper,
        "the no-fix-and-no-retained-fix case is not reported")

print("test_work_mode_jt808_contract: PASS")
