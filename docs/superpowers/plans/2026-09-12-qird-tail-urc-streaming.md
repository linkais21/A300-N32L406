# QIRD Tail URC Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve a complete QIRD payload when asynchronous URCs appear between its binary body and terminal result, then publish V3.021/V3.022 for real-device OTA testing.

**Architecture:** Convert `qird_collect_payload` from whole-response buffering to header/body/tail streaming. Reuse `s_line_buf` for text phases and `s_at_resp` for only the declared body, so no static RAM is added.

**Tech Stack:** C99, EC800M UART DMA, Python C host harness, ARM GNU Toolchain.

## Global Constraints

- Keep `AT_RESP_MAX` at 512 and QIRD chunk size at 400.
- Treat exactly the declared body length as opaque binary.
- Dispatch complete URCs before the QIRD header and between body and result.
- Accept only a complete `OK` line after the body; reject `ERROR`.
- Preserve HTTP, Range, Flash, package, signature, and Bootloader contracts.
- Do not commit, push, upload, deploy, or program hardware.

---

### Task 1: Tail URC RED test

**Files:**
- Modify: `tools/tests/test_ec800m_urc_demux.py`

- [x] Feed a 400-byte body, then enough valid receive URCs to exceed the old 511-byte aggregate limit, then the real `OK`.
- [x] Assert the callback receives all 400 body bytes and the intervening URCs remain serviceable.
- [x] Run `python tools/tests/test_ec800m_urc_demux.py`; expect failure at the 400-byte callback assertion.

### Task 2: Streaming collector GREEN implementation

**Files:**
- Modify: `src/ec800m.c`

- [x] Parse the `+QIRD` line using bounded decimal parsing and reject lengths greater than the requested chunk or response buffer.
- [x] Copy exactly the declared body bytes to `s_at_resp` without result scanning.
- [x] Process following text lines until `OK` or `ERROR`, forwarding other lines through the existing URC path.
- [x] Run the focused EC800M test; expect PASS.

### Task 3: Regression and resource gates

**Files:**
- Test only.

- [x] Run EC800M, FOTA diagnostics, platform-flow, resume, modem handoff, parser, and package tests.
- [x] Run clean ARM build, release guard, RAM guard, and stack guard with no compiler warning.

### Task 4: Release V3.021/V3.022

**Files:**
- Modify: `release_identity.json`, `include/config.h`, generated `include/build_version.h`, version tests and release-guard canonical hashes.
- Create: `artifacts_release16_final/V3.021/*`
- Create: `artifacts_release17_final/V3.022/*`

- [x] Build and validate V3.021 combined SWD image.
- [x] Increment only release identity and build V3.022 OTA image.
- [x] Validate every manifest hash, OTA header/CRC, memory bounds, and `git diff --check`.
