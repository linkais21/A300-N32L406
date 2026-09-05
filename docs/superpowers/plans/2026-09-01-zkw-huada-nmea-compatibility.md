# Zhongkewei and Huada NMEA Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the common bounded NMEA parser accept the observed Zhongkewei and Huada GGA/RMC variants without weakening checksum, coordinate, date, time, or overflow validation.

**Architecture:** Keep one talker-independent GGA/RMC parser. Treat optional RMC motion fields as zero only when the field is empty, while retaining strict parsing for every non-empty value; cover GN, BD, and GB samples and both five- and seven-decimal-minute coordinates with host replays.

**Tech Stack:** C99 N32L406 firmware, Python host-compiled replay tests, ARM GNU Toolchain, Make release gates.

## Global Constraints

- Preserve the ISR/main-loop two-slot handoff and bounded static memory.
- Do not log raw NMEA, coordinates, device identifiers, or secrets.
- Continue rejecting invalid checksums, malformed non-empty numbers, invalid time/date/direction, and arithmetic overflow.
- Do not change Flash layout, protocol fields, positioning hardware configuration, or the 4096-byte RAM warning threshold.
- Do not commit, flash, deploy, or send device commands.

---

### Task 1: Four-profile NMEA replay coverage

**Files:**
- Modify: `tools/tests/test_nmea_replay.py`

**Interfaces:**
- Consumes: `gps_rx_isr(uint8_t)`, `gps_process(void)`, `gps_get_data(void)`, `gps_get_diag(void)`
- Produces: host replay coverage for GN/BD/GB GGA and RMC behavior

- [ ] Add hand-derived, anonymized samples matching Zhongkewei GPS+BD, Zhongkewei BDS-only, Huada BDS-only, and Huada BDS RTK field structures.
- [ ] Assert the Zhongkewei BDS-only RMC with empty course is accepted and stores heading `0.0f` while preserving date/time.
- [ ] Assert Huada RTK seven-decimal-minute coordinates parse successfully.
- [ ] Assert a malformed non-empty course remains rejected.
- [ ] Run `python tools/tests/test_nmea_replay.py` and verify the new empty-course case fails before production changes.

### Task 2: Minimal common-parser compatibility

**Files:**
- Modify: `src/gps.c`

**Interfaces:**
- Consumes: bounded `parse_decimal(const char *, double *)`
- Produces: RMC optional speed/course handling shared by all supported talkers

- [ ] Parse an empty speed or course field as `0.0`; pass every non-empty field through `parse_decimal` unchanged.
- [ ] Keep the existing `knots >= 0`, `0 <= heading < 360`, time/date, direction, checksum, and integer-overflow validation.
- [ ] Run `python tools/tests/test_nmea_replay.py` and verify all compatibility and rejection cases pass.

### Task 3: Regression and release verification

**Files:**
- Verify: `src/gps.c`, `tools/tests/test_nmea_replay.py`, generated `build/a300_firmware.hex`

**Interfaces:**
- Produces: buildable firmware and HIL-ready HEX hash

- [ ] Run the NMEA, EC800M, JT808, identity, FOTA, and external-Flash directed host tests.
- [ ] Run `mingw32-make all` and `mingw32-make release-gate`.
- [ ] Run `git diff --check` for touched files and calculate the HEX SHA-256.
- [ ] Report automated results separately from required Zhongkewei/Huada HIL validation.
