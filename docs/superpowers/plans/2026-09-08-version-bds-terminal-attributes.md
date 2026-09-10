# Version, BeiDou Status, and Terminal Attributes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Release firmware `V3.001` with a fixed OTA model contract, correct BeiDou `0x0200` status, and one complete proactive `0x0107` upload per authenticated channel per boot.

**Architecture:** Keep firmware, OTA, JT808 model, and manufacturer identities as separate named constants validated from one JSON release contract. Extract terminal-attribute encoding into a reusable bounded encoder that accepts the EC800M driver's established 19/20-character hexadecimal ICCID contract, then let the JT808 session layer own per-channel boot delivery state. Preserve the existing platform-query route by calling the same encoder on the requesting channel; proactive delivery completes on modem delivery and never waits for a platform acknowledgement.

**Tech Stack:** C99, ARM GNU Toolchain, Python host harnesses, PowerShell version generation, Spring Boot 3.4/Java 17/Maven.

## Global Constraints

- Firmware version is exactly `T360-A300_406_20260823000000,V3.001`.
- Future versions retain the fixed prefix and increment the three-digit revision.
- OTA device model is exactly `A300-406`.
- JT/T 808 terminal model is exactly `T360-A300`; manufacturer ID is exactly `70110`.
- Current valid fixes set status bits 1 and 19. A retained position reported during sleep clears bit1 but preserves bit19 when its trusted source was a BeiDou fix.
- Terminal type is `0x000D`; GNSS capability is `0x02`; communications capability is `0x20`.
- CH0 and configured CH3 each upload `0x0107` once after their first successful authentication per boot.
- Do not create a branch or commit. Do not flash hardware or deploy the FOTA platform.
- Firmware outputs remain only in `A300-first/build/`.

---

### Task 1: Freeze Release Identity and OTA Model

**Files:**
- Create: `release_identity.json`
- Modify: `include/config.h`
- Modify: `include/build_version.h`
- Modify: `gen_version.ps1`
- Modify: `tools/release_guard.py`
- Modify: `tools/tests/test_build_version_refresh.py`
- Modify: `tools/tests/test_feature_guards.py`
- Modify: `tools/tests/test_terminal_identity.py`
- Modify: `fota-platform/backend/src/main/resources/application.yml`
- Modify: `fota-platform/backend/src/main/resources/application-prod.yml`
- Modify: `fota-platform/backend/src/main/java/com/a300/fota/service/FirmwareService.java`
- Test: existing backend `FirmwareService` tests or a focused new model-normalization unit test.

**Interfaces:**
- Produces: `FW_VERSION_STR`, `FW_OTA_MODEL_STR`, `FW_JT808_MODEL_STR`, and `FW_MANUFACTURER_ID_STR`.
- Consumes: `release_identity.json` from `gen_version.ps1` and `tools/release_guard.py`.

- [ ] Write tests asserting the exact V3.001 version, fixed prefix/revision relation, all three identity strings, and FOTA normalization to `A300-406`.
- [ ] Run the focused Python and Maven tests; verify they fail only because current values are V3.000/A300/A300_406/CYHLL.
- [ ] Add the JSON contract, update C macros, make version generation read the JSON, and make release guard reject inconsistent versions or models.
- [ ] Update FOTA defaults and normalize legacy `A300`, `A300_406`, and `T360-A300*` aliases to `A300-406`.
- [ ] Re-run focused tests and verify they pass.

### Task 2: Encode BeiDou Positioning Status

**Files:**
- Modify: `include/jt808.h`
- Modify: `src/jt808.c`
- Modify: `tools/tests/test_jt808_first_location.py`
- Modify: `tools/tests/test_work_mode_jt808_contract.py`

**Interfaces:**
- Produces: `LOC_FLAG_BEIDOU_FIXED` as bit19.
- Consumes: `gps_data_t.fix_quality` and the existing `historical_position` flag.

- [ ] Extend real C harness assertions so a valid live fix has both bit1 and bit19, while a retained sleep position clears bit1 and preserves bit19 from the trusted BeiDou source.
- [ ] Run the two focused tests and verify the retained-position bit19 assertion fails because the historical branch clears both bits.
- [ ] Set bit19 alongside bit1 in the common compact encoder, and clear only bit1 in the online historical-position adjustment.
- [ ] Re-run the focused tests and verify they pass without changing ACC or coordinate semantics.

### Task 3: Share Complete `0x0107` Attribute Encoding

**Files:**
- Create: `include/jt808_terminal_info.h`
- Create: `src/jt808_terminal_info.c`
- Modify: `Makefile`
- Modify: `src/jt808_params.c`
- Modify: `include/jt808_params.h`
- Modify: `tools/tests/test_terminal_identity.py`

**Interfaces:**
- Produces: `jt808_terminal_info_result_t jt808_terminal_info_encode(const jt808_terminal_t *terminal, uint8_t *body, uint16_t capacity, uint16_t *length)`.
- Consumes: canonical terminal identity, EC800M ICCID, and release identity macros.

- [ ] Add exact-byte harness checks for terminal type `000D`, manufacturer `70110`, model `T360-A300`, derived ID, BCD ICCID, zero hardware-version length, V3.001 firmware string, GNSS `02`, and communications `20`.
- [ ] Add exact-byte tests for a synthetic EC800M ICCID containing `D`, lowercase normalization, and 19-character leading-zero padding; reject only characters outside `0-9A-Fa-f`, invalid lengths, invalid identity, null arguments, and insufficient output capacity.
- [ ] Run the terminal-info harness and verify failures identify the old incomplete encoder.
- [ ] Implement bounded hexadecimal-nibble ICCID validation/encoding and the shared body encoder without dynamic allocation; preserve each modem-reported nibble so `D0` encodes as byte `0xD0` rather than fabricating a decimal digit.
- [ ] Replace the `0x8107` query implementation with the shared encoder and preserve failure general responses.
- [ ] Re-run terminal identity and query-routing tests and verify they pass.

### Task 4: Deliver `0x0107` Once Per Boot Per Channel

**Files:**
- Modify: `include/jt808.h`
- Modify: `src/jt808.c`
- Modify: `tools/tests/test_jt808_dual_session.py`
- Create: `tools/tests/test_jt808_boot_terminal_info.py` if the dual-session harness cannot express retry timing cleanly.

**Interfaces:**
- Produces: per-channel terminal-info states reset by `jt808_init()` and processed by `jt808_process()`.
- Consumes: authentication success, TCP channel generation/link state, shared terminal-info encoder, and existing definite/ambiguous send semantics.

- [ ] Add CH0/CH3 tests proving each first authentication queues exactly one proactive `0x0107`, reconnect/re-auth does not resend, and `jt808_init()` permits a new boot upload.
- [ ] Add tests proving definite failure retries with bounded delay, ambiguous send completes, and a later platform `0x8107` query still gets a response.
- [ ] Prove that a successful proactive modem send marks the channel complete without waiting for any platform `0x8001` acknowledgement to `0x0107`.
- [ ] Run the focused boot-delivery tests and verify they fail because proactive per-channel state does not exist.
- [ ] Add a channel-specific raw send helper and bounded pending/sent/retry state; process it outside the receive callback so authentication handling stays non-blocking.
- [ ] Re-run focused tests and verify exact once-per-boot behavior for both channels.

### Task 5: Documentation, Full Regression, and Firmware Build

**Files:**
- Modify: `README.md`
- Modify: `fota-platform/README.md` or the nearest existing OTA operator documentation if present.
- Regenerate: `include/build_version.h`
- Generate only under: `build/`

**Interfaces:**
- Documents: the four distinct identities, version increment rule, status bits, and reboot upload contract.

- [ ] Update concise operator/developer documentation with V3.xxx increment examples and OTA model `A300-406`.
- [ ] Run all modified/related Python host tests plus existing SMS/runtime regressions.
- [ ] Run backend focused tests and `mvn test`; do not start Docker or services.
- [ ] Run `gen_version.ps1`, clean ARM build, `make release-guard`, and `make ram-guard`.
- [ ] Run `git diff --check` separately in each available repository boundary and inspect the scoped diff.
- [ ] Regenerate BIN in `A300-first/build/`, then report final version, sizes, timestamps, and SHA256 hashes.
- [ ] Record that dual-platform authentication, real ICCID, BeiDou bit19, reboot behavior, and RAM margin require real-device/HIL verification.

### Task 6: Close HIL-Discovered ICCID and Sleep-Status Regressions

**Files:**
- Modify: `src/jt808_terminal_info.c`
- Modify: `src/jt808.c`
- Modify: `tools/tests/test_terminal_identity.py`
- Modify: `tools/tests/test_jt808_first_location.py`
- Modify: `tools/tests/test_work_mode_jt808_contract.py`

**Interfaces:**
- Consumes: `ec800m_get_iccid()`, whose established output is 19 or 20 hexadecimal characters, and `historical_position`, which identifies a retained trusted fix used during sleep.
- Produces: an 83-byte `0x0107` body for 19/20-character hexadecimal ICCIDs, plus sleep `0x0200` status with bit1 clear and bit19 preserved.

- [x] Add an exact-byte encoder regression for a synthetic 20-character ICCID containing `D` and run `python tools/tests/test_terminal_identity.py`; expect the current decimal-only validator to reject it.
- [x] Accept `0-9A-Fa-f` nibbles, normalize only while encoding, and rerun `python tools/tests/test_terminal_identity.py`; expect PASS with the literal synthetic byte sequence asserted by the harness.
- [x] Add a real-frame assertion that a retained sleep location clears status bit1 but preserves bit19, then run `python tools/tests/test_jt808_first_location.py`; expect the current historical branch to fail that assertion.
- [x] Change the historical branch to clear only `LOC_FLAG_GPS_FIXED`, update the source-contract assertion, and rerun `python tools/tests/test_jt808_first_location.py` and `python tools/tests/test_work_mode_jt808_contract.py`; expect PASS.
- [x] Run the focused `0x0107`, dual-session, location, work-mode, modem-parser, and release-contract tests, followed by `make all`, `make release-guard`, `make ram-guard`, and `git diff --check`.
- [ ] Report that the exact EC800M ICCID, platform decoding of nibble `D`, automatic no-ack delivery, and sleep status display still require real-device/HIL verification.
