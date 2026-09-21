#!/usr/bin/env python3
"""Grade an A300 production startup capture without echoing sensitive log data."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys


MANDATORY = ("boot", "flash", "modem", "jt808", "gnss")
GPS_COUNTERS = re.compile(r"\b(RX|GGA|RMC|CS|FMT)=(\d+)\b")
HEALTH_FIX = re.compile(r"\bGPS=(\d+)\b")


def grade(lines) -> dict[str, object]:
    stages = {name: False for name in MANDATORY}
    gps_counters: dict[str, int] | None = None
    fix = False
    fota_401 = False

    for raw_line in lines:
        line = raw_line.strip()
        if "[BOOT] ready" in line:
            stages["boot"] = True
        if "JEDEC=684015" in line:
            stages["flash"] = True
        if "[4G] ready" in line:
            stages["modem"] = True
        if "[808] ch0 ONLINE" in line:
            stages["jt808"] = True
        if "HTTP response status=401" in line:
            fota_401 = True
        if line.startswith("[HEALTH]"):
            match = HEALTH_FIX.search(line)
            if match is not None and int(match.group(1)) == 1:
                fix = True
        if line.startswith("[GPS]"):
            parsed = {name: int(value) for name, value in GPS_COUNTERS.findall(line)}
            if all(name in parsed for name in ("RX", "GGA", "RMC", "CS", "FMT")):
                gps_counters = parsed

    if gps_counters is not None:
        stages["gnss"] = (
            gps_counters["RX"] > 0 and gps_counters["GGA"] > 0 and
            gps_counters["RMC"] > 0 and gps_counters["CS"] == 0 and
            gps_counters["FMT"] == 0
        )
    return {"stages": stages, "fix": fix, "fota_401": fota_401}


def summarize(result: dict[str, object]) -> str:
    stages = result["stages"]
    assert isinstance(stages, dict)
    passed = all(stages.get(name) is True for name in MANDATORY)
    stage_text = " ".join(
        f"{name.upper()}={'PASS' if stages.get(name) else 'FAIL'}" for name in MANDATORY
    )
    gnss = "FIX" if result["fix"] else "NO_FIX"
    warning = " WARNING=FOTA_401" if result["fota_401"] else ""
    return f"CORE={'PASS' if passed else 'FAIL'} {stage_text} GNSS={gnss}{warning}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Grade a sanitized A300 startup self-test")
    parser.add_argument("capture", type=Path)
    args = parser.parse_args(argv)
    try:
        with args.capture.open("r", encoding="utf-8", errors="replace") as capture:
            result = grade(capture)
    except OSError as exc:
        print(f"CORE=FAIL INPUT=UNREADABLE ERROR={type(exc).__name__}", file=sys.stderr)
        return 2
    print(summarize(result))
    stages = result["stages"]
    assert isinstance(stages, dict)
    return 0 if all(stages.get(name) is True for name in MANDATORY) else 1


if __name__ == "__main__":
    raise SystemExit(main())
