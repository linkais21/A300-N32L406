#!/usr/bin/env python3
"""Static contract for ACC-aware STOP1 wake handling."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]


def strip_c_comments(source: str) -> str:
    """Remove C comments before evaluating positive source contracts."""
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"//[^\r\n]*", "", source)


MAIN = strip_c_comments((ROOT / "src/main.c").read_text(encoding="utf-8"))
SLEEP = strip_c_comments((ROOT / "src/work_mode_sleep.c").read_text(encoding="utf-8"))
HW_INIT = strip_c_comments((ROOT / "src/hw_init.c").read_text(encoding="utf-8"))
JT808 = strip_c_comments((ROOT / "src/jt808.c").read_text(encoding="utf-8"))
GPS = strip_c_comments((ROOT / "src/gps.c").read_text(encoding="utf-8"))
WORK_MODE = strip_c_comments((ROOT / "src/work_mode.c").read_text(encoding="utf-8"))


def function_body(source: str, name: str) -> str:
    match = re.search(rf"\b{name}\s*\([^;]*?\)\s*\{{", source, re.S)
    if match is None:
        raise AssertionError(f"missing function body: {name}")
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


def braced_block(source: str, opening_brace: int) -> str:
    depth = 0
    for index in range(opening_brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[opening_brace + 1:index]
    raise AssertionError("unterminated STOP1 wake branch")


def stop1_wake_branch(process: str) -> str:
    match = re.search(
        r"if\s*\(\s*s_wake\s*!=\s*WORK_SLEEP_WAKE_NONE\s*\)\s*\{",
        process,
    )
    if match is None:
        raise AssertionError("missing STOP1 pending-wake branch")
    return braced_block(process, match.end() - 1)


def stop1_wfi_return_branch(process: str) -> str:
    start = process.find("wake_reason = s_wake;")
    if start < 0:
        raise AssertionError("missing STOP1 WFI wake_reason path")
    end = process.find("service_online_window();", start)
    if end < 0:
        raise AssertionError("STOP1 WFI wake_reason path has no service boundary")
    return process[start:end]


def switch_case(function: str, label: str) -> str:
    match = re.search(
        rf"case\s+{re.escape(label)}\s*:(.*?)(?=\b(?:break|case|default)\b)",
        function,
        re.DOTALL,
    )
    if match is None:
        raise AssertionError(f"missing switch case: {label}")
    return match.group(1)


def main() -> None:
    process = function_body(SLEEP, "work_mode_sleep_process")
    pending_branch = stop1_wake_branch(process)
    wfi_return_branch = stop1_wfi_return_branch(process)
    if "work_mode_sleep_process(15000U, wake)" not in MAIN:
        raise AssertionError("main loop does not pass pending wake state to STOP1 service")
    if "jt808_request_reregister()" in pending_branch:
        raise AssertionError("pending STOP1 wake path must not force JT808 re-registration")
    if "hw_acc_is_on()" not in wfi_return_branch:
        raise AssertionError("STOP1 wake path does not sample ACC physical state")
    if not re.search(r"source\s*=\s*stop1_wake", wfi_return_branch):
        raise AssertionError("STOP1 wake path lacks source=stop1_wake ACC diagnostic")
    if "jt808_request_reregister()" in wfi_return_branch:
        raise AssertionError("STOP1 wake path must not force JT808 re-registration")

    # Final hardware contract: Q9 is an inverting NPN level shifter, so the
    # physical PA12 collector is low when external ACC is ON. Keep this
    # assertion source-level so a polarity regression fails before HIL.
    acc_fn = function_body(HW_INIT, "hw_acc_is_on")
    if not re.search(r"return\s*!\s*hw_acc_pin_high\s*\(\s*\)", acc_fn):
        raise AssertionError("ACC contract requires PA12 low level = external ACC ON")

    # STOP1 must report a retained/trusted location after GNSS is disabled;
    # using the live GPS object alone would produce an invalid/zero position.
    retained_decl = re.search(
        r"(?:static\s+)?gps_data_t\s+"
        r"(?P<name>\w*(?:stop1|last_trusted|retained)\w*)\s*;",
        JT808,
        re.IGNORECASE,
    )
    send_work_mode = function_body(JT808, "jt808_send_location_work_mode")
    retained_accessor = re.search(
        r"gps_\w*(?:stop1|last_trusted|retained)\w*\s*\(",
        send_work_mode,
        re.IGNORECASE,
    )
    retained_used = (
        retained_decl is not None and
        retained_decl.group("name") in send_work_mode
    )
    if not retained_used and retained_accessor is None:
        raise AssertionError("JT808 lacks a retained last-trusted GPS snapshot")
    if "gps_capture_last_trusted" not in GPS:
        raise AssertionError("GPS lacks a capture hook for the last trusted snapshot")
    if "gps_get_last_trusted" not in GPS:
        raise AssertionError("GPS lacks a retained last-trusted snapshot accessor")
    work_process = function_body(MAIN, "work_mode_process")
    gps_off_case = switch_case(work_process, "WORK_ACTION_GPS_OFF")
    gps_on_case = switch_case(work_process, "WORK_ACTION_GPS_ON")
    if not re.search(r"gps_enable\s*\(\s*false\s*\)", gps_off_case):
        raise AssertionError("STOP1 path lacks GNSS disable hook")
    capture = gps_off_case.find("gps_capture_last_trusted()")
    disable = gps_off_case.find("gps_enable(false)")
    if capture < 0 or disable < 0 or capture > disable:
        raise AssertionError("STOP1 must retain a trusted snapshot before GNSS disable")
    if not re.search(r"gps_enable\s*\(\s*true\s*\)", gps_on_case):
        raise AssertionError("wake path lacks GNSS restore hook")
    if "gps_resume_after_wake()" not in gps_on_case:
        raise AssertionError("wake path must reinitialize GNSS without wiping the retained snapshot")

    # Confirm both default STOP1 cadence values are represented in the
    # work-mode/JT808 implementation and that the online service path cannot
    # force a fresh registration.
    defaults = MAIN + JT808 + WORK_MODE
    if not re.search(r"report_stopped_s\s*=\s*180", defaults):
        raise AssertionError("STOP1 location cadence default 180 s is missing")
    if not re.search(r"heartbeat_s\s*=\s*180", defaults):
        raise AssertionError("STOP1 heartbeat cadence default 180 s is missing")
    service = function_body(SLEEP, "service_online_window")
    if "jt808_request_reregister()" in service:
        raise AssertionError("STOP1 online service must not force re-registration")
    print("ACC STOP1 contract: PASS")


if __name__ == "__main__":
    main()
