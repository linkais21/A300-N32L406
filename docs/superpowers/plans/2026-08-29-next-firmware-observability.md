# A300-406 Next Firmware Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore observable EC800M/JT808 registration transmission, generate trustworthy build timestamps, and expose the exact DA218E I2C failure boundary.

**Architecture:** Keep the existing blocking EC800M transport and JT808 state machine, but isolate QISEND prompt/result handling and add bounded retry diagnostics. Generate the version header before every release build. Preserve hardware I2C and add read-only bus/stage diagnostics.

**Tech Stack:** C11 embedded firmware, N32L40x vendor SDK, ARM GCC, GNU Make, Python 3 host tests and release tooling.

## Global Constraints

- Do not rewrite EC800M as a fully asynchronous state machine.
- Do not change DA218E pins, PCB strategy, or introduce more guessed addresses.
- Do not print authentication secrets.
- All waits and retries remain bounded.
- Do not auto-flash physical hardware.
- Preserve unrelated user changes; do not commit this dirty working tree.

---

### Task 1: QISEND Prompt and Result Handling

**Files:**
- Modify: `src/ec800m.c`
- Test: `tools/tests/test_ec800m_qisend.py`

**Interfaces:**
- Consumes: existing `at_send_wait_owned()`, `usart_send_buf()`, `ec800m_tcp_send()`.
- Produces: unchanged `int ec800m_tcp_send(uint8_t ch, const uint8_t *data, uint16_t len)` with stage-specific diagnostics and reliable bare-prompt recognition.

- [ ] **Step 1: Write a failing host/contract test**

Assert that the source has a dedicated bare-prompt waiter, recognizes `>` without CR/LF, reports `prompt`, `payload`, and `result` failures, releases `AT_OWNER_TCP` on every exit, and reports `SEND OK` success without exposing frame contents.

- [ ] **Step 2: Run the test and verify RED**

Run: `python tools/tests/test_ec800m_qisend.py`

Expected: FAIL because the dedicated prompt/result diagnostic contract is absent.

- [ ] **Step 3: Implement the minimal transport fix**

Add a bounded prompt wait that reads the DMA ring and accepts a bare `>` byte. Refactor `ec800m_tcp_send()` into explicit command/prompt/payload/result stages, print `[4G-TX] ch=%u len=%u`, `[4G-TX] fail stage=...`, or `[4G-TX] ch=%u SEND OK`, and release ownership through one cleanup path.

- [ ] **Step 4: Verify GREEN and regression tests**

Run:

```text
python tools/tests/test_ec800m_qisend.py
python tools/tests/test_agnss_vendor_stream.py
```

Expected: PASS.

### Task 2: JT808 Send-Failure Backoff and Registration Diagnostics

**Files:**
- Modify: `src/jt808.c`
- Test: `tools/tests/test_jt808_registration_tx.py`

**Interfaces:**
- Consumes: `ec800m_tcp_send()` return value and existing registration state.
- Produces: bounded retry timing while IDLE, REGISTERING only after a successful send, and non-secret response metadata logs.

- [ ] **Step 1: Write a failing test**

Assert source behavior for a 5-second send-failure retry deadline, successful transition to REGISTERING only after return `0`, and receive diagnostics containing channel/message ID/serial/result without auth-code logging.

- [ ] **Step 2: Run the test and verify RED**

Run: `python tools/tests/test_jt808_registration_tx.py`

Expected: FAIL because failed IDLE sends are currently retried immediately after each blocking timeout.

- [ ] **Step 3: Implement minimal state-machine changes**

Track `s_register_attempt_ms`; suppress another IDLE registration attempt until 5 seconds have elapsed after a failed send; retain the existing 5-second REGISTERING response retry. Add receive metadata at validated frame dispatch and redact authentication material.

- [ ] **Step 4: Verify GREEN and terminal identity regression**

Run:

```text
python tools/tests/test_jt808_registration_tx.py
python tools/tests/test_terminal_identity.py
```

Expected: PASS.

### Task 3: Release-Time Build Version Generation

**Files:**
- Modify: `tools/build_dev_release.py`
- Modify: `gen_version.ps1` only if needed to make output deterministic and UTF-8 safe
- Test: `tools/tests/test_build_version_refresh.py`

**Interfaces:**
- Consumes: release tool `run()` and `include/build_version.h`.
- Produces: a freshly generated version header before `make -B all`, with the generated timestamp embedded in the built ELF.

- [ ] **Step 1: Write a failing release-tool test**

Assert that version generation occurs before both make invocations, failure aborts the release, and the generated timestamp is recorded or verified against the ELF strings.

- [ ] **Step 2: Run the test and verify RED**

Run: `python tools/tests/test_build_version_refresh.py`

Expected: FAIL because the release script currently invokes make without refreshing the header.

- [ ] **Step 3: Implement version generation**

Generate `build_version.h` from Python using Asia/Shanghai local time and stable ASCII month formatting, or invoke the checked-in generator with an explicit failure check. Keep `FW_FULL_VERSION` unchanged and refresh only build number/date fields.

- [ ] **Step 4: Verify GREEN**

Run:

```text
python tools/tests/test_build_version_refresh.py
python tools/tests/test_dev_release_manifest.py
```

Expected: PASS.

### Task 4: DA218E Bus-Level and Stage Diagnostics

**Files:**
- Modify: `src/i2c_accel.c`
- Test: `tools/tests/test_da218e_i2c_contract.py`

**Interfaces:**
- Consumes: existing hardware I2C transactions and PB6/PB7 input registers.
- Produces: one idle-level line and a summarized first-failure stage per probe attempt.

- [ ] **Step 1: Extend the failing contract test**

Require `[ACCEL] bus SCL=%u SDA=%u`, a finite failure-stage enum covering BUS/START/ADDR-W/REG/RESTART/ADDR-R/DATA, and summarized stage logs. Require the existing four compatibility probes and bounded timeouts to remain.

- [ ] **Step 2: Run the test and verify RED**

Run: `python tools/tests/test_da218e_i2c_contract.py`

Expected: FAIL because bus-level and stage diagnostics are absent.

- [ ] **Step 3: Implement read-only diagnostics**

Return a failure-stage value from the ID read helper, sample PB6/PB7 before probing, log one line per failed address/attempt or a compact summary, and preserve successful Chip ID handling. Do not change pin configuration or address list.

- [ ] **Step 4: Verify GREEN**

Run: `python tools/tests/test_da218e_i2c_contract.py`

Expected: PASS.

### Task 5: Integrated Build and Release Package

**Files:**
- Generated: `build/*`, `bootloader/build/*`
- Generated: `dist/dev-key/next-observability/<UTC-build-id>/*`

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces: verified Combined, Bootloader, APP, signed package, maps, ELF files, and SHA256 manifest.

- [ ] **Step 1: Run focused regression tests**

Run all tests created or changed in Tasks 1-4 plus Bootloader platform, debug printf, signed package, and manifest tests. Expected: all PASS.

- [ ] **Step 2: Build a clean forced release**

Run:

```text
python tools/build_dev_release.py --key .keys/dev-p256-private.pem --output dist/dev-key/next-observability
```

Expected: APP and Bootloader forced builds complete with no compiler warnings; manifest path printed.

- [ ] **Step 3: Inspect release artifacts**

Verify Combined image exists, compute SHA256, confirm ELF contains new Build timestamp and all new diagnostic strings, and confirm memory-map guards passed.

- [ ] **Step 4: Report handoff**

Provide the exact Combined image path, SHA256, expected first-boot log signatures, tests run, and explicitly state that physical DA218E/JT808 success still requires the user's next device log.
