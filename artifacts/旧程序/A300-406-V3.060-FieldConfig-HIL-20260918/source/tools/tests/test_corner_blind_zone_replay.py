#!/usr/bin/env python3
"""Contract checks for corner-report handoff to blind-zone FIFO."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
JT = (ROOT / "src/jt808.c").read_text(encoding="utf-8")
GPS = (ROOT / "src/gps.c").read_text(encoding="utf-8")
MAKE = (ROOT / "Makefile").read_text(encoding="utf-8")

def require(cond, msg):
    if not cond:
        raise AssertionError(msg)

require('#include "motion_corner.h"' in JT, "JT808 does not include corner policy")
require("motion_corner_step" in JT and "motion_corner_peek_candidate" in JT,
        "corner policy is not stepped/peeked by location scheduler")
require("blind_zone_append(&record)" in JT,
        "corner send failure has no blind-zone append path")
require("motion_corner_consume_candidate(&s_motion_corner)" in JT,
        "corner candidate is never consumed after completion")
# Consumption must be guarded by successful append or direct send; pending,
# busy and IO-error paths retain the candidate for a later retry.
for block in re.findall(r"blind_zone_result_t stored = blind_zone_append\(&record\);([\s\S]{0,700})", JT):
    require("BLIND_ZONE_OK" in block, "blind-zone append result is unchecked")
require("s_corner_append_pending = true" in JT,
        "append pending state does not retain failed corner point")
require("heading_update_ms" in GPS,
        "GPS lacks RMC-only heading freshness timestamp")
require(re.search(r"parse_gga[\s\S]{0,1200}heading_update_ms", GPS) is None,
        "GGA must not update heading freshness")
require(re.search(r"parse_rmc[\s\S]{0,1600}heading_update_ms", GPS) is not None,
        "RMC must update heading freshness")
require("src/motion_corner.c" in MAKE, "motion corner source missing from build")
print("test_corner_blind_zone_replay: PASS")
