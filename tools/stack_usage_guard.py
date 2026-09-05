#!/usr/bin/env python3
"""Reject regressions in audited ARM GCC stack-usage reports."""

from pathlib import Path
import argparse
import sys


LIMITS = {
    "process_frame": 192,
    "send_frame_channel": 128,
    "jt808_send_auth_to": 128,
    "jt808_send_location_to": 128,
    "jt808_send_location": 224,
    "cfg_set_auth_code": 128,
    "gps_rx_isr": 64,
    "gps_process": 128,
    "dispatch_nmea": 256,
    "process_urc": 192,
}


def load(paths: list[Path]) -> dict[str, int]:
    usage: dict[str, int] = {}
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            fields = line.split("\t")
            if len(fields) < 2:
                continue
            name = fields[0].rsplit(":", 1)[-1]
            try:
                usage[name] = int(fields[1])
            except ValueError:
                continue
    return usage


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", nargs="+", type=Path)
    args = parser.parse_args()
    missing = [path for path in args.reports if not path.is_file()]
    if missing:
        print("stack-guard: missing report(s): " + ", ".join(map(str, missing)))
        return 1
    usage = load(args.reports)
    failed = False
    for name, limit in LIMITS.items():
        actual = usage.get(name)
        if actual is None:
            print(f"stack-guard: FAIL {name}: no compiler evidence")
            failed = True
        elif actual > limit:
            print(f"stack-guard: FAIL {name}: {actual} B > {limit} B")
            failed = True
        else:
            print(f"stack-guard: {name} {actual} B <= {limit} B")
    if failed:
        return 1
    print("stack-guard: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
