# JT808 Online Location Extensions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Emit the complete 67-byte A300 `0x0200` location body on live online reports while retaining the existing 34-byte blind-zone v3 payload and 64-byte Flash record layout.

**Architecture:** Split location encoding into a mandatory 28-byte core, a compact blind-zone extension set, and a full online extension set. Live send buffers use a new 67-byte bound; blind-zone records continue using `BLIND_ZONE_LOCATION_MAX=40` and never call the full encoder.

**Tech Stack:** C99 N32L406 firmware, Python host-compiled JT808 tests, ARM GNU Toolchain, Make release gates.

## Global Constraints

- Full online extension order is `01,03,30,31,61,EC,E3` with body length exactly 67 bytes.
- Blind-zone v3 payload stays 34 bytes and `BLIND_ZONE_LOCATION_MAX` stays 40 bytes.
- No Flash format, capacity, address, metadata, generation, or recovery-state changes.
- Use only bounded static/stack buffers; no dynamic allocation.
- Clamp conversions before integer casts and retain JT808 big-endian encoding.
- Do not commit, push, flash, deploy, or send live device commands.

---

### Task 1: Wire-format RED tests

**Files:**
- Modify: `tools/tests/test_jt808_dual_session.py`
- Modify: `tools/tests/test_blind_zone_replay.py` if required by the existing harness

- [ ] Add a fixed GPS/config/ADC/CSQ fixture and assert the live `0x0200` body length is 67.
- [ ] Decode and assert each TLV ID, length, order, and big-endian value.
- [ ] Assert the blind-zone append payload remains 34 bytes and replay remains valid.
- [ ] Run the directed tests and verify the new live-body assertion fails before production changes.

### Task 2: Bounded dual encoders

**Files:**
- Modify: `src/jt808.c`

- [ ] Add a 67-byte online location maximum independent from `BLIND_ZONE_LOCATION_MAX`.
- [ ] Factor the 28-byte core and retain the compact `31/30` blind-zone extension encoder.
- [ ] Add full online extensions `01/03/30/31/61/EC/E3` using current config, ADC, GNSS, and modem snapshots.
- [ ] Route direct `jt808_send_location_to()` and non-blind direct-response location paths through the full encoder.
- [ ] Keep `blind_zone_record_t.location` and append/replay paths on the compact encoder.
- [ ] Run JT808 and blind-zone host tests until green.

### Task 3: Release verification

**Files:**
- Verify: `src/jt808.c`, directed tests, `build/a300_firmware.hex`

- [ ] Run JT808, blind-zone, GPS, identity, EC800M, FOTA, and external-Flash directed tests.
- [ ] Run `mingw32-make all` and `mingw32-make release-gate`.
- [ ] Run `git diff --check` and calculate the HEX SHA-256.
- [ ] Report that online wire format is host-verified and that field values still require packet-capture HIL verification.
