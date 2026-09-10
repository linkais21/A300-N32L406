# SMS Runtime Closure Implementation Plan

> **For agentic workers:** Execute inline task-by-task with RED-GREEN tests. Do not create a branch or commit.

**Goal:** Close every supported F39 command's persistence-to-runtime path and produce a test firmware in `build/`.

**Architecture:** Use binary-safe EC800M response matching, one work-mode periodic location scheduler, JT808 broadcast to all online sessions, and explicit post-commit runtime effects. Keep platform/session state bounded and static.

**Tech Stack:** C99, ARM GNU Toolchain, N32L40x SPL, Python host C harnesses, GNU Make.

## Global Constraints

- Preserve all existing user changes and the current `main` branch.
- Do not commit, push, flash, deploy, or create a branch.
- Generate firmware only under `A300-first/build`.
- Write a failing regression test before each production behavior change.

---

### Task 1: Binary-Safe EC800M Send Completion

**Files:** `src/ec800m.c`, `src/ec800m_at_response.c`, `include/ec800m_at_response.h`, `tools/tests/test_ec800m_urc_demux.py`

- [ ] Add a host case where binary data containing `0x00` precedes `SEND OK`.
- [ ] Run the case and verify the current matcher times out.
- [ ] Add a bounded length-aware token matcher and use it in AT waits.
- [ ] Run EC800M response, demux, QISEND, and recovery tests.

### Task 2: Single Scheduler and Dual-Platform Location

**Files:** `src/jt808.c`, `src/work_mode.c`, `src/main.c`, `tools/tests/test_jt808_dual_session.py`, `tools/tests/test_work_mode_policy.py`

- [ ] Add failures for one ten-second periodic owner and broadcast to CH0/CH3.
- [ ] Add a failure for an independently authenticated FIP first-fix report.
- [ ] Remove ordinary periodic sends from the legacy timer while retaining
  corner and first-fix handling.
- [ ] Make work-mode reports broadcast to all authenticated sessions and
  advance deadlines for wire-confirmed or ambiguous sends.

### Task 3: F39 Runtime Consumers

**Files:** `src/f39_config_adapter.c`, `include/f39_config_adapter.h`, `src/f39_reply.c`, `include/f39_reply.h`, `src/at_config.c`, `src/jt808.c`, `include/jt808.h`, `src/main.c`, `src/work_mode.c`, `tools/tests/test_f39_end_to_end.py`, `tools/tests/test_sms_work_mode_commands.py`

- [ ] Add failures for FREQ enabling sleep reports and GPSDUP changing the live policy.
- [ ] Add failures for MODEL/CAR runtime registration identity refresh.
- [ ] Add failures for configured GMT offset and SPEED alarm consumption.
- [ ] Add a failure proving APN changes restart the PDP data session.
- [ ] Implement the minimal post-commit effects and bounded runtime state.
- [ ] Run all F39, work-mode, JT808, GPS, and modem focused tests.

### Task 4: Target Build and Delivery

**Files:** `build/a300_firmware.{elf,hex,bin,map}` and existing build metadata.

- [ ] Run the relevant full host regression set with compiler-required mode.
- [ ] Run `make clean` only for generated `build/` outputs, then `make all`.
- [ ] Run `make release-guard`, `make ram-guard`, and `git diff --check`.
- [ ] Record hashes, sizes, build timestamp, changed files, and HIL checks.
