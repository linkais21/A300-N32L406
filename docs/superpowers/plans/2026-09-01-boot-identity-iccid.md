# Boot Identity and ICCID Completeness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate complete EC800M identities and print IMEI, PID, ICCID, and configured server endpoints once before the first JT808 TCP connection attempt after every boot.

**Architecture:** Add bounded pure parsers for 15-digit IMEI and 19/20-digit ICCID responses, retain the last complete value, and retry the ICCID initialization step a finite number of times. Move the boot identity/server summary to the TCP manager boundary immediately before connection while retaining the JT808 terminal-identity diagnostic after synchronization.

**Tech Stack:** C99 N32L406 firmware, host C harnesses, Python contract tests, ARM GNU Toolchain.

## Global Constraints

- ICCID accepts only exactly 19 or 20 ASCII digits; IMEI accepts exactly 15 digits.
- Support `+QCCID:` with or without whitespace before the digits.
- A truncated/malformed read cannot overwrite a previously complete identity.
- Retry is bounded and identity failure cannot indefinitely block network registration.
- Print no auth code, APN password, key, token, phone number, or location.
- Do not commit, push, flash, deploy, or send real commands.

---

### Task 1: Identity parser RED tests

**Files:**
- Modify: `tools/tests/test_ec800m_urc_demux.py` or create a focused host test
- Modify: `src/ec800m.c`

- [ ] Assert 19- and 20-digit QCCID responses parse completely.
- [ ] Assert optional whitespace is accepted.
- [ ] Assert 12-digit, 21-digit, and alphanumeric values are rejected.
- [ ] Assert getters terminate all nonzero-size destination buffers.
- [ ] Run the focused test and confirm failure before implementation.

### Task 2: Bounded initialization behavior

**Files:**
- Modify: `src/ec800m.c`

- [ ] Use the strict parser for IMEI and ICCID initialization responses.
- [ ] Retry ICCID a fixed finite number of times before advancing to SIM check.
- [ ] Log identity readiness with lengths, without printing values at the modem layer.
- [ ] Preserve a complete prior identity if a later read is malformed.

### Task 3: Pre-connect boot summary

**Files:**
- Modify: `src/tcp_manager.c`
- Modify: `src/jt808.c` only if needed to avoid duplicate semantics
- Test: focused TCP manager/identity host contract

- [ ] Print `[BOOT-ID] IMEI=... PID=... ICCID=...` once before the first connection attempt.
- [ ] Print `[BOOT-SERVER] MAIN=host:port BACKUP=...` immediately afterward.
- [ ] Show invalid identity as `INVALID(len=N)` rather than treating it as ready.
- [ ] Retain `[DEVICE]` for final JT808 terminal ID and PID source diagnostics.

### Task 4: Verification

**Files:**
- Verify: modified production/tests and `build/a300_firmware.hex`

- [ ] Run EC800M, TCP manager, terminal identity, JT808, GPS, and blind-zone directed tests.
- [ ] Run `mingw32-make all` and `mingw32-make release-gate`.
- [ ] Run `git diff --check` and calculate the HEX SHA-256.
- [ ] Report that actual full ICCID and log ordering require UART HIL confirmation.
