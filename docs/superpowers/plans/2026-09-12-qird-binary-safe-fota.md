# Binary-safe QIRD FOTA Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make EC800M OTA downloads preserve binary payloads containing AT result-looking byte sequences and produce actionable verification failure logs.

**Architecture:** Replace generic line-result waiting for TCP QIRD with a bounded length-aware collector modeled on the working G452 implementation. Keep HTTP/Range and Flash state machines unchanged, add focused failure diagnostics, then create a V3.019 SWD baseline and V3.020 OTA target.

**Tech Stack:** C99, EC800M UART DMA, N32L406 external NOR FOTA, Python host-test harness, ARM GNU Toolchain.

## Global Constraints

- QIRD payload bytes are opaque until the declared payload length is consumed.
- Only a result line after the payload can complete the QIRD transaction.
- Keep the 400-byte QIRD chunk and bounded cooperative continuation behavior.
- Do not change OTA HTTP API, Flash layout, cryptographic acceptance, or boot contract.
- Do not commit, push, upload, deploy, or flash hardware.
- Real-device completion remains a HIL verification requirement.

---

### Task 1: Reproduce embedded result bytes

**Files:**
- Modify: `tools/tests/test_ec800m_urc_demux.py`
- Test: `tools/tests/test_ec800m_urc_demux.py`

- [x] Add a modem fixture that separates an eight-byte payload containing `\r\nOK\r\n` from the real QIRD terminal result.
- [x] Run `python tools/tests/test_ec800m_urc_demux.py` and verify it fails because no eight-byte payload reaches the callback.

### Task 2: Add the binary-safe QIRD collector

**Files:**
- Modify: `src/ec800m.c`
- Test: `tools/tests/test_ec800m_urc_demux.py`

- [x] Add a bounded owned collector that parses the declared length before recognizing the terminal result.
- [x] Route TCP QIRD reads through the collector while preserving callbacks and the pending mask.
- [x] Run the focused test and verify it passes.

### Task 3: Add verification failure diagnostics

**Files:**
- Modify: `src/fota.c`
- Modify: `tools/tests/test_fota_diagnostics.py`

- [x] Add test assertions for non-sensitive verification stage logs.
- [x] Verify the diagnostics test fails before implementation.
- [x] Add logs for header, read, SHA-256, signature, CRC, vector, BCR, authorization, and pending failures.
- [x] Run diagnostics and platform-flow tests and verify they pass.

### Task 4: Regression and release pair

**Files:**
- Modify: release identity/version expectations as required by the existing release workflow.
- Create: `artifacts_release14/V3.019/*`
- Create: `artifacts_release15/V3.020/*`

- [x] Run focused EC800M/FOTA tests, firmware build, release guard, RAM guard, and stack guard.
- [x] Build V3.019 and validate its combined SWD image and manifest.
- [x] Increment only the release identity and build the V3.020 OTA package.
- [x] Validate versions, sizes, hashes, `git diff --check`, and scoped differences.
