# GPS/URC Phase 2 Stack Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove NMEA parsing from UART4 ISR and eliminate scanf/strtod from normal GNSS/EC800M paths.

**Architecture:** UART4 publishes complete sentences into a bounded two-slot queue and `gps_process()` parses one per iteration. Dedicated bounded numeric/URC parsers replace generic libc conversion routines.

**Tech Stack:** C99, ARM GNU Toolchain, N32L40x SPL, Python-driven host C harnesses.

## Global Constraints

- ISR only receives bytes, terminates complete sentences, and publishes a slot.
- No dynamic allocation, unbounded waits, or silent buffer overwrite.
- Preserve existing JT808/GPS/EC800M observable behavior.
- Do not commit, flash, deploy, or discard unrelated worktree changes.

---

### Task 1: Deferred NMEA parsing

**Files:**
- Modify: `src/gps.c`
- Test: `tools/tests/test_nmea_replay.py`

**Interfaces:**
- Consumes: UART4 bytes through `gps_rx_isr(uint8_t)`.
- Produces: one bounded parse operation per `gps_process()` call.

- [ ] Add a host replay assertion that a complete valid RMC sentence does not update `gps_get_data()` until `gps_process()` runs, and that two queued sentences retain order.
- [ ] Run `python tools/tests/test_nmea_replay.py` and verify the new assertion fails against synchronous ISR parsing.
- [ ] Implement two-slot publication with explicit ready flags and make `gps_process()` consume at most one sentence.
- [ ] Re-run the replay test and verify valid, invalid checksum, half-frame, and queue-full cases.

### Task 2: Bounded NMEA numeric conversion

**Files:**
- Modify: `src/gps.c`
- Test: `tools/tests/test_nmea_replay.py`

**Interfaces:**
- Produces: internal bounded decimal parser returning scaled signed integers.

- [ ] Add literal fixtures for negative/positive coordinates, altitude, HDOP, knots and malformed/overflow fields.
- [ ] Verify RED by requiring no update for malformed numeric data while the old `atof/atoi` path accepts it partially.
- [ ] Replace `atof`, `atoi`, and checksum `strtol` usage with bounded parsers and scaled arithmetic.
- [ ] Verify all NMEA fixtures pass and output fields remain within explicit tolerances.

### Task 3: Bounded EC800M URC parsing

**Files:**
- Modify: `src/ec800m.c`
- Test: `tools/tests/test_ec800m_urc_demux.py`

**Interfaces:**
- Consumes: complete modem lines.
- Produces: channel/open/close/recv/CSQ events only for exact valid grammar.

- [ ] Add malformed and boundary URC fixtures that must not invoke QIRD, close a link, or change CSQ.
- [ ] Run the URC harness and verify an old partial `sscanf` match causes the intended RED failure.
- [ ] Implement exact prefix plus bounded unsigned integer parsing for QIOPEN, QIURC recv/closed and CSQ.
- [ ] Re-run EC800M QIRD, QISEND and URC demux regressions.

### Task 4: Stack/link guards and full verification

**Files:**
- Modify: `Makefile`
- Modify: `tools/stack_usage_guard.py`
- Test: `tools/tests/test_nmea_replay.py`, `tools/tests/test_ec800m_urc_demux.py`

**Interfaces:**
- Produces: build failure when critical stack frames regress or forbidden libc parsers return.

- [ ] Add audited limits for `gps_rx_isr`, `gps_process`, and `process_urc`.
- [ ] Add a link/map check rejecting live `sscanf`, `atof`, or `strtod` symbols in the application.
- [ ] Run directed host tests, `make all`, bootloader rebuild, `make release-gate`, `git diff --check`, and hash the new HEX.
- [ ] Report HIL-only checks separately: GNSS valid fix, AUTH/ONLINE, `STK_PEAK`, `RAM_GAP`, and `F` after cold boot.
