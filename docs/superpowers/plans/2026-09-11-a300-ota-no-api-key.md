# A300 OTA No API Key Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align A300_406 firmware and the Spring FOTA platform with the original no-API-Key OTA contract.

**Architecture:** Device checks require no shared API key. Downloads and progress are authorized by an independent opaque 24-character task token; firmware keeps it only in RAM, while the legacy config key field remains solely for Flash-layout compatibility.

**Tech Stack:** C99 firmware, Python host contract tests, Spring Boot 3.4.10, Java 17, JDBC, JUnit.

## Global Constraints

- Do not alter Flash configuration layout or remove signature, SHA-256, Range, BCR, rollback, timeout, or retry checks.
- Do not expose secrets or token values in debug logs.
- Do not deploy, restart production services, flash hardware, or commit changes.

### Task 1: Firmware request contract

**Files:**
- Modify: `A300-first/src/fota.c`
- Test: `A300-first/tools/tests/test_fota_no_api_key_contract.py`

**Interfaces:** `begin_check`, `fota_start_request`, and `send_request` must operate with an empty `device_api_key`; GET requests must not contain `X-Device-Key`.

- [ ] Write a source contract test asserting no key gate/header and retaining `X-OTA-Token`.
- [ ] Run `python tools/tests/test_fota_no_api_key_contract.py`; verify RED against current source.
- [ ] Remove only the three firmware key dependencies and keep all other request headers/validation.
- [ ] Run the test and existing FOTA parser/package tests; verify GREEN.

### Task 2: Platform token authorization

**Files:**
- Modify: `fota-platform/backend/src/main/java/com/a300/fota/security/DeviceApiKeyFilter.java`
- Modify: `fota-platform/backend/src/main/java/com/a300/fota/web/DeviceUpdateController.java`
- Modify: `fota-platform/backend/src/main/java/com/a300/fota/service/OtaTaskService.java`
- Test: `fota-platform/backend/src/test/java/com/a300/fota/DevicePullContractIT.java`

**Interfaces:** `downloadTask(taskId, token, range)` validates token; `checkForUpdate` returns a URL containing the task token; task authorization rejects absent/mismatched/terminal tokens.

- [ ] Add integration assertions for check/download without `X-Device-Key`, token-required download, wrong-token rejection, and valid Range.
- [ ] Run the focused Maven test; verify RED.
- [ ] Bypass the API-key filter for device OTA routes, append token to stable URL, and enforce token equality in `authorizeDownload`.
- [ ] Add a unique `download_token` index for new and existing MySQL databases, and omit token-bearing fields from admin task responses.
- [ ] Run focused tests and verify GREEN.

### Task 3: Progress endpoint

**Files:**
- Modify: `fota-platform/backend/src/main/java/com/a300/fota/web/DeviceUpdateController.java`
- Modify: `fota-platform/backend/src/main/java/com/a300/fota/service/OtaTaskService.java`
- Modify: `fota-platform/backend/src/main/java/com/a300/fota/repository/FotaRepository.java` only if an existing repository operation cannot record fields
- Test: `fota-platform/backend/src/test/java/com/a300/fota/FotaApiSmokeTest.java`

**Interfaces:** `POST /api/device/updates/progress` accepts the existing device payload and `X-OTA-Token`, validates task/device/version, updates bounded progress, and returns 2xx only for a matching active task.

- [ ] Add tests for valid token, missing/wrong token, invalid state/progress, and terminal task.
- [ ] Require complete byte count and 100% progress for downloaded/install/success reports.
- [ ] Run focused test; verify RED.
- [ ] Implement controller DTO parsing and service mutation using existing task fields and upgrade-log service.
- [ ] Run all backend unit/integration tests available; verify GREEN.

### Task 4: Firmware token propagation and verification

**Files:**
- Modify: `A300-first/src/fota.c`
- Do not modify: Bootloader authorization, BCR, marker, or configuration Flash structures
- Test: `A300-first/tools/tests/test_fota_platform_flow.py`

- [ ] Add a host contract test proving parsed `downloadToken` reaches the download URL and status request construction without entering logs, status output, or Flash records.
- [ ] Run it RED.
- [ ] Keep the token in RAM through check-to-download/status paths, with a bounded best-effort status window that never blocks BCR commit or reset.
- [ ] Run firmware FOTA tests and build guards.

### Task 5: Final verification

- [ ] Run `git diff --check` in both nested repositories.
- [ ] Run firmware focused tests, `make all`, `make release-guard`, and `make ram-guard` when toolchain is available.
- [ ] Run `mvn test` and `mvn verify` in `fota-platform/backend` when Maven/dependencies are available.
- [ ] Report automated results separately from required real-device/HIL OTA verification.
