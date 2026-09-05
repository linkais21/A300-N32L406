# EC800M/JT808 Downlink Diagnostics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add privacy-safe logs that identify the exact EC800M/JT808 downlink boundary where the registration response is lost.

**Architecture:** Instrument the existing EC800M QIURC/QIRD transaction and JT808 stream/frame parser without changing protocol state or retry behavior. Reuse host harnesses to prove each rejection reason and ensure no payload or authentication secret is logged.

**Tech Stack:** C99 embedded firmware, N32L40x SPL, ARM GCC, Python-driven host C tests.

## Global Constraints

- Do not change endpoints, identity fields, timeouts, retry counts, or session transitions.
- Do not print payload bytes, authentication codes, full identities, or locations.
- Keep all waits bounded and all diagnostics outside ISRs.
- Preserve unrelated dirty-worktree changes; do not commit, push, deploy, or flash.

---

### Task 1: EC800M QIURC/QIRD boundary diagnostics

**Files:**
- Modify: `src/ec800m.c`
- Modify: `tools/tests/test_ec800m_urc_demux.py`

**Interfaces:**
- Consumes: `process_urc(const char *)`, `at_send_wait(const char *, const char *, uint32_t)`, `ec800m_parse_qird_response(...)`.
- Produces: `[4G-RX] ch=N event=recv`, `[4G-RX] ch=N qird=N`, and fixed QIRD failure logs.

- [ ] Add host assertions capturing diagnostic output for a successful fragmented, binary-safe QIRD transaction and for a malformed/incomplete QIRD response.
- [ ] Run `python tools/tests/test_ec800m_urc_demux.py`; expect RED because the logs are absent.
- [ ] Add minimal logs around validated QIURC parsing, QIRD AT completion, and QIRD response parsing; never print response content.
- [ ] Re-run `python tools/tests/test_ec800m_urc_demux.py`; expect PASS.

### Task 2: JT808 stream and frame rejection diagnostics

**Files:**
- Modify: `src/jt808.c`
- Modify: `tools/tests/test_jt808_registration_tx.py`

**Interfaces:**
- Consumes: `jt808_on_recv(uint8_t, const uint8_t *, uint16_t)` and `process_frame(...)`.
- Produces: `[808-RX] ch=N bytes=N`, accepted-frame metadata, and fixed `drop=` reasons.

- [ ] Extend the host harness to inject a valid 0x8100 plus short, bad-escape, checksum, and body-length failures; assert only metadata/reasons are logged.
- [ ] Run `python tools/tests/test_jt808_registration_tx.py`; expect RED because diagnostic contracts are absent.
- [ ] Add bounded metadata and rejection logs. Treat an unknown escape suffix as `drop=escape` rather than silently copying or discarding it.
- [ ] Re-run the directed test; expect PASS and verify no auth body text appears in logs.

### Task 3: Regression, build, and artifact verification

**Files:**
- Verify: EC800M/JT808 tests and firmware build outputs.

**Interfaces:**
- Consumes: Tasks 1-2.
- Produces: a fresh `build/a300_firmware.hex` for user-controlled HIL flashing.

- [ ] Run EC800M QISEND, URC, network-registration and JT808 registration/session/identity tests.
- [ ] Run `make all`, `make release-guard`, and `make ram-guard` with the configured STM32CubeIDE make executable.
- [ ] Run `git diff --check` on task files and inspect the scoped diff for secrets or behavior changes.
- [ ] Record HEX timestamp and SHA-256; report that physical flashing and HIL validation were not performed.
