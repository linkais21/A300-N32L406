# Task7-F39 Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every approved F39 SMS command execute the retained A300 behavior through A300_406 services, with atomic `DUALSET` and bounded replies.

**Architecture:** Add a focused F39 parser/executor between the existing SMS FIFO and A300_406 configuration/services. Selectively port validation and behavior from the A300 reference while keeping all MCU/SDK/build code native to A300_406.

**Tech Stack:** C99 embedded firmware, host GCC C harnesses, Python test launchers, existing A300_406 flash configuration/JT808/GNSS/relay/EC800M services.

## Global Constraints

- This is functional migration; never copy N32G452 SDK, startup, linker, clock, interrupt, peripheral-driver or build-project files.
- Keep only the 17 approved F39 command roots in the design specification.
- `DUALSET` is atomic: zero state changes or side effects on any failure; one persistence operation on success.
- Static allocation only; command maximum 192 bytes; SMS FIFO remains exactly two entries.
- Preserve OTA, blind-zone external-Flash storage, Huada/CSIP AGNSS, core JT808 and user-owned uncommitted changes.
- Version remains `T360-A300_406_20260823000000,V3.000`.

---

### Task 1: Add the platform-neutral F39 command core

**Files:**
- Create: `include/f39_command.h`
- Create: `src/f39_command.c`
- Create: `tools/tests/test_f39_parser.py`
- Modify: `Makefile`

**Interfaces:**
- Produces: `f39_result_t f39_parse(const uint8_t *data, uint16_t len, f39_request_t *out)`
- Produces: typed operation enum and bounded argument fields for all approved commands.

- [ ] Write a failing host C harness covering all approved command roots, query/set distinctions, exact comma/`*` delimiters, 192-byte bound, trailing garbage and all removed roots.
- [ ] Run `python tools/tests/test_f39_parser.py`; expect failure because `f39_parse` is absent.
- [ ] Implement bounded, case-insensitive parsing without allocation or mutation of the caller buffer.
- [ ] Run the parser harness and require PASS with no compiler warnings.
- [ ] Commit `feat: add bounded F39 command parser`.

### Task 2: Add transactional configuration application

**Files:**
- Create: `include/f39_config_adapter.h`
- Create: `src/f39_config_adapter.c`
- Create: `tools/tests/test_f39_config.py`
- Modify: `src/f39_command.c`

**Interfaces:**
- Consumes: typed `f39_request_t` from Task 1.
- Produces: `bool f39_prepare_config(const f39_request_t *, const device_config_t *, f39_transaction_t *)` and `f39_result_t f39_commit_config(f39_transaction_t *)`.

- [ ] Write failing tests for IP/FIP, FREQ, HBT, MODEL, SPEED, APN, GPSDUP, MLG, CAR, GPSBDS, GMTSET and PID range/character rules.
- [ ] Add persistence stubs and assert invalid inputs cause zero saves and zero side effects.
- [ ] Implement candidate-copy validation and a single save boundary.
- [ ] Assert persistence failure retains old configuration and returns failure.
- [ ] Run `python tools/tests/test_f39_config.py`; require PASS.
- [ ] Commit `feat: map F39 configuration commands`.

### Task 3: Implement atomic DUALSET

**Files:**
- Create: `tools/tests/test_f39_dualset.py`
- Modify: `src/f39_command.c`
- Modify: `src/f39_config_adapter.c`

**Interfaces:**
- Produces: one `f39_transaction_t` containing candidate configuration and a side-effect bitmask.

- [ ] Write failing tests where the last subcommand is invalid and assert byte-for-byte unchanged configuration, zero saves and zero side effects.
- [ ] Test duplicate keys, nested `DUALSET`, empty items, repeated separators, `RESET`, `RELAY`, unknown roots and more subcommands than the fixed bound.
- [ ] Implement full preflight over the candidate configuration.
- [ ] Implement one persistence commit followed by deterministic effects: timers, network, GNSS and remaining refreshes.
- [ ] Test successful multi-command execution performs exactly one save and each requested effect at most once.
- [ ] Run `python tools/tests/test_f39_dualset.py`; require PASS.
- [ ] Commit `feat: make F39 DUALSET atomic`.

### Task 4: Add actions, queries and bounded replies

**Files:**
- Create: `include/f39_reply.h`
- Create: `src/f39_reply.c`
- Create: `tools/tests/test_f39_actions.py`
- Modify: `src/f39_command.c`

**Interfaces:**
- Produces: `f39_result_t f39_execute(const f39_request_t *, f39_platform_t *, f39_reply_t *)`.
- `f39_platform_t` contains injected bounded callbacks for config save, reconnect, timers, GNSS mode, relay, reset scheduling and query data.

- [ ] Write failing tests for `PARAM`, all queries, relay safety, delayed reset, GPSBDS receiver dispatch and bounded/sanitized replies.
- [ ] Implement query response builders that never return APN passwords or credentials.
- [ ] Implement relay cut only with valid fix and speed below 20 km/h; always allow restore.
- [ ] Implement reset as response-first plus scheduled reset callback.
- [ ] Test response-buffer exhaustion produces a bounded failure or defined multipart reply without truncation success.
- [ ] Run `python tools/tests/test_f39_actions.py`; require PASS.
- [ ] Commit `feat: execute F39 actions and replies`.

### Task 5: Integrate F39 with the SMS production chain

**Files:**
- Modify: `src/at_config.c`
- Modify: `include/at_config.h`
- Modify: `src/peripherals.c`
- Modify: `src/main.c`
- Create: `tools/tests/test_f39_end_to_end.py`

**Interfaces:**
- Consumes: existing sender+command FIFO.
- Produces: `+CMT -> queue -> f39_execute -> sms_send` production behavior.

- [ ] Write a failing end-to-end harness covering two different senders and configuration/action/reply results.
- [ ] Replace the debug `handle_cmd()` dispatch for SMS with the F39 executor while retaining serial/JT808 behavior unchanged.
- [ ] Route the bounded reply to the original FIFO sender and handle SMS-send busy/failure without blocking the watchdog.
- [ ] Verify removed commands never reach a platform callback.
- [ ] Run `python tools/tests/test_f39_end_to_end.py` and all existing SMS tests; require PASS.
- [ ] Commit `feat: connect F39 execution to SMS`.

### Task 6: Close Task7-F39 verification

**Files:**
- Modify: `tools/tests/test_feature_guards.py`
- Create: `docs/task7-f39-verification.md`

**Interfaces:**
- Consumes all Task 1-5 behavior.
- Produces a host verification record; target build/hardware gates remain Task10.

- [ ] Run every F39 parser/config/DUALSET/action/end-to-end test plus existing SMS, RAM and feature guards.
- [ ] Scan release sources for removed commands and forbidden N32G452 platform files/symbols.
- [ ] Run `git diff --check` and verify the six user-owned dirty files were not included in Task7-F39 commits.
- [ ] Document exact PASS/SKIP evidence and Task10 target-toolchain/hardware gates.
- [ ] Commit `test: verify Task7 F39 execution`.
