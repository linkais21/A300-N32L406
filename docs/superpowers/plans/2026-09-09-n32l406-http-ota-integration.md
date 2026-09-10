# N32L406 HTTP OTA Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver authenticated, device-pull HTTP OTA for A300-T9/N32L406 with stable Range resume, signed-manifest validation, immediate installation reset, and power-loss-safe Bootloader installation.

**Architecture:** The firmware keeps the existing signed candidate/BCR pipeline and adds three bounded units: generated version identity, a pure check-response parser, and a dual-sector checkpoint store. `fota.c` coordinates modem channel 1, boot/6-hour checks, authenticated HTTP, resume, verification, and reset. The Spring platform accepts the exact N32L406 signed package, verifies it with the release public key, requires the device key for check/download, and keeps assigned tasks resumable until a new-version check-in or operator cancellation.

**Tech Stack:** C99, ARM GNU Toolchain, N32L40x SPL, BY25Q16 NOR Flash, EC800M raw TCP/HTTP; Java 17, Spring Boot 3.4, JDBC, JCA ECDSA P-256; Vue 3, TypeScript, Vite; Python/C host harnesses.

## Global Constraints

- Modify only `D:\A300_406_tools\A300_406\A300-first` and `D:\A300_406_tools\A300_406\fota-platform`.
- Treat both `D:\A300_Tools\A300-N32G452\A300-N32G452\app\src` and `app\ota_platform` as read-only references.
- Never copy N32G452 Flash addresses, package headers, BCR records, product IDs, hardware IDs, binaries, or build inputs into N32L406.
- Device model is exactly `A300-406`; transport is HTTP/1.1 on channel 1 with `X-Device-Key`.
- `FKEY` accepts 16 to 31 printable ASCII characters and the value must never appear in logs or query responses.
- Check once after modem/identity readiness and every 21,600,000 ms thereafter.
- Only whitelist assignments produce update tasks; no JT808 `0x8108`, TCP 8800, MQTT, gateway callback, redirects, chunked bodies, or expiring tokens.
- Commit `BCR_PENDING` only after full package verification; reset immediately after the verified BCR commit.
- Download checkpoints and Bootloader install progress must survive torn writes and repeated power loss.
- A server response being written does not prove device receipt; old-version checks must not terminate a resumable task.
- Preserve all existing user changes. Do not commit, push, deploy, flash hardware, restart production services, or alter production data.
- The current `fota-platform` directory is not detected as a Git worktree; validate its changed-file scope directly instead of claiming a platform `git diff` result.

---

## File Structure

### Firmware application

- Create `include/fota_check_parser.h`: bounded check-response DTO and parser interface.
- Create `src/fota_check_parser.c`: order-independent JSON field parser with duplicate/type rejection.
- Create `include/fota_checkpoint.h`: checkpoint record and dual-slot persistence interface.
- Create `src/fota_checkpoint.c`: two-sector sequence/CRC/commit-marker journal.
- Modify `include/build_version.h`, `gen_version.ps1`, `release_identity.json`, `tools/build_dev_release.py`: one version counter in the app and signed manifest.
- Modify `include/flash_config.h`, `src/flash_config.c`: v4 append-only API key storage and OTA base URL default.
- Modify `include/f39_command.h`, `src/f39_command.c`, `src/f39_config_adapter.c`, `src/f39_reply.c`: `FKEY` command and redacted query.
- Modify `include/fota.h`, `src/fota.c`, `Makefile`: OTA check coordinator, authenticated requests, resume integration, and immediate reset.
- Reuse `terminal_identity_sync()` from `include/terminal_identity.h`; do not add a second identity derivation path.

### Bootloader

- Modify `bootloader/include/bootloader_config.h`: expose the 2 KiB internal page transaction size separately from the 256-byte copy buffer.
- Modify `bootloader/src/image_install.c`: erase/program/readback/commit one internal page at a time and resume only at committed page boundaries.
- Extend `bootloader/host_model.py` and create `tools/tests/test_bootloader_powercut.py`: exhaustive modeled power-cut coverage.

### Platform

- Modify `backend/src/main/java/com/a300/fota/config/FotaProperties.java`: configured release public-key path.
- Replace RSA signing behavior in `backend/src/main/java/com/a300/fota/service/CryptoService.java` with SHA-256 and ECDSA P-256 verification only.
- Modify `OtaImageMetadata.java`, `OtaImageParser.java`, `FirmwareService.java`: exact 124-byte N32L406 manifest parsing and upload validation.
- Modify `FirmwareRelease.java`, `FirmwareResponse.java`, and JDBC mapping only where needed to expose manifest terminology while retaining physical columns.
- Modify `DeviceApiKeyFilter.java`, `DeviceUpdateController.java`, `OtaTaskService.java`, and `CheckUpdateResponse.java`: authenticated four-field response and nonterminal resumable task behavior.
- Modify `frontend/src/types.ts` and `frontend/src/App.vue`: signed-package labels and metadata.
- Update `README.md` and replace stale statements in `A300-设备主动HTTP-OTA契约.md` with the approved N32L406 contract.

---

### Task 1: Freeze One Firmware Version Counter

**Files:**
- Modify: `release_identity.json`
- Modify: `gen_version.ps1`
- Modify: `include/build_version.h`
- Modify: `tools/build_dev_release.py`
- Modify: `tools/release_guard.py`
- Test: `tools/tests/test_build_version_refresh.py`
- Test: `tools/tests/test_dev_release_manifest.py`
- Test: `tools/tests/test_release_identity_contract.py`

**Interfaces:**
- Produces: `#define FW_VERSION_COUNTER <u32>` in `build_version.h`.
- Produces: `release_identity.json["firmware_version_counter"]` as the approved nonzero unsigned 32-bit counter.
- Invariant: the counter compiled into the App equals the `--version-counter` passed to `sign_firmware.py`.

- [ ] **Step 1: Add failing generator and release-contract tests**

Assert that generated headers include a decimal `FW_VERSION_COUNTER`, that zero/out-of-range values fail, and that `build_dev_release.py` rejects a CLI value different from `release_identity.json`.

```python
assert '#define FW_VERSION_COUNTER  3001UL' in generated
assert manifest["version_counter"] == identity["firmware_version_counter"]
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```powershell
python tools/tests/test_build_version_refresh.py
python tools/tests/test_dev_release_manifest.py
python tools/tests/test_release_identity_contract.py
```

Expected: at least the new `FW_VERSION_COUNTER` assertion fails because the macro and identity field do not exist.

- [ ] **Step 3: Implement the single-source version counter**

Set the current approved counter to `3001`, load it in both generators, emit it as `FW_VERSION_COUNTER`, and require `build_dev_release.py --version-counter` to equal it before building. Pass that same value to `sign_firmware.py`.

```c
#define FW_VERSION_COUNTER  3001UL
```

- [ ] **Step 4: Extend release guard checks**

Require a nonzero u32 JSON value and an exact numeric macro match, while preserving existing version-string checks and volatile build-date normalization.

- [ ] **Step 5: Run the focused tests and confirm GREEN**

Run the three commands from Step 2. Expected: all pass.

- [ ] **Step 6: Review the task diff without committing**

Run `git diff --check` and inspect only the Task 1 files. Do not create a commit.

---

### Task 2: Persist And Configure The Device API Key

**Files:**
- Modify: `include/flash_config.h`
- Modify: `src/flash_config.c`
- Modify: `include/f39_command.h`
- Modify: `src/f39_command.c`
- Modify: `include/f39_config_adapter.h`
- Modify: `src/f39_config_adapter.c`
- Modify: `src/f39_reply.c`
- Test: `tools/tests/test_flash_config_migration.py`
- Test: `tools/tests/test_f39_config.py`
- Test: `tools/tests/test_f39_actions.py`
- Create: `tools/tests/test_fota_key_config.py`

**Interfaces:**
- Produces: `CFG_DEVICE_API_KEY_LEN = 32` and `device_config_t.device_api_key[32]` appended after every current v3 field.
- Produces: `cfg_set_device_api_key_result(const char key[CFG_DEVICE_API_KEY_LEN])` with rollback on persistence failure.
- Produces: `F39_OPERATION_FKEY` and effect `F39_EFFECT_FOTA_RECHECK`.

- [ ] **Step 1: Add failing v3-to-v4 migration tests**

Build a valid old v3 record whose `data_len` ends before `device_api_key`, then assert all old bytes survive, the new key is empty, the OTA base URL defaults to `http://fota.lhhn.net`, and the rewritten record is v4 with a valid CRC and commit marker.

- [ ] **Step 2: Add failing FKEY parser/transaction tests**

Cover 15, 16, 31, and 32-byte keys; nonprintable input; persistence failure rollback; `FKEY?`; and confirm no reply contains the configured key.

```c
assert(parse_and_commit("FKEY,1234567890ABCDEF") == F39_RESULT_OK);
assert(strcmp(cfg.device_api_key, "1234567890ABCDEF") == 0);
assert(strstr(reply, cfg.device_api_key) == NULL);
```

- [ ] **Step 3: Run the four focused tests and confirm RED**

```powershell
python tools/tests/test_flash_config_migration.py
python tools/tests/test_f39_config.py
python tools/tests/test_f39_actions.py
python tools/tests/test_fota_key_config.py
```

Expected: compilation/assertion failures for the missing v4 field and FKEY operation.

- [ ] **Step 4: Implement append-only v4 loading and storage**

Bump `CFG_VERSION` to 4, recognize exact old v3 length separately, initialize the new tail from defaults, and retain dual-slot generation selection. Never reinterpret a corrupt or oversized record as an older version.

- [ ] **Step 5: Implement FKEY configuration and redacted query**

Accept only one argument of 16 to 31 bytes in `0x20..0x7E`, persist a candidate copy atomically, set `F39_EFFECT_FOTA_RECHECK`, and reply only with `FKEY,CONFIGURED=0|1`.

- [ ] **Step 6: Run focused tests and confirm GREEN**

Run the four commands from Step 3. Expected: all pass.

- [ ] **Step 7: Review RAM and diff impact**

Run `make all`, then `python tools/map_ram_guard.py app build/a300_firmware.map` and `git diff --check`. Expected: the firmware links and the RAM guard passes. Do not commit.

---

### Task 3: Add A Bounded Update-Check Parser

**Files:**
- Create: `include/fota_check_parser.h`
- Create: `src/fota_check_parser.c`
- Modify: `Makefile`
- Create: `tools/tests/test_fota_check_parser.py`

**Interfaces:**
- Produces:

```c
typedef struct {
    bool update_available;
    uint32_t version_code;
    uint32_t size;
    char download_url[128];
} fota_check_response_t;

bool fota_check_parse(const char *json, uint16_t length,
                      fota_check_response_t *out);
```

- [ ] **Step 1: Write a compiling host harness with failing cases**

Cover fragmented-body assembly at the caller boundary, arbitrary field order, JSON whitespace, `false` with no extra required fields, valid `true`, missing fields, duplicate fields, wrong types, escaped strings, negative/overflow numbers, URL overflow, trailing garbage, and unknown extra fields. Unknown fields are rejected so the device contract stays bounded and explicit.

- [ ] **Step 2: Run the parser test and confirm RED**

Run `python tools/tests/test_fota_check_parser.py`.

Expected: compile failure because the header/source do not exist.

- [ ] **Step 3: Implement the minimal parser**

Use cursor-and-length parsing only; do not call `strstr()` over unterminated modem data and do not allocate memory. Track a seen-bit per field and require exactly one occurrence of each required field.

- [ ] **Step 4: Run parser tests and confirm GREEN**

Run `python tools/tests/test_fota_check_parser.py`. Expected: C99 `-Wall -Wextra -Werror` harness passes.

- [ ] **Step 5: Add the source to the ARM build and review**

Add `src/fota_check_parser.c` to `C_SRCS`, run `git diff --check`, and do not commit.

---

### Task 4: Make Download Checkpoints Torn-Write Safe

**Files:**
- Create: `include/fota_checkpoint.h`
- Create: `src/fota_checkpoint.c`
- Modify: `include/fota.h`
- Modify: `src/fota.c`
- Modify: `Makefile`
- Replace assertions in: `tools/tests/test_fota_resume.py`
- Create: `tools/tests/test_fota_checkpoint_powercut.py`
- Modify: `tools/tests/test_ext_flash_layout.py`

**Interfaces:**
- Consumes: caller-held `EXT_FLASH_OWNER_OTA` lock.
- Produces:

```c
#define FOTA_CHECKPOINT_SLOT_A (EXT_FLASH_RESUME_ADDR + 0x2000UL)
#define FOTA_CHECKPOINT_SLOT_B (EXT_FLASH_RESUME_ADDR + 0x3000UL)

bool fota_checkpoint_load(const char *url, uint32_t expected_length,
                          fota_checkpoint_t *out);
bool fota_checkpoint_commit(const fota_checkpoint_t *record);
bool fota_checkpoint_clear(void);
```

- [ ] **Step 1: Write the NOR/power-cut model tests**

Model one-way programming, sector erase, CRC, final marker, wrap-safe sequence selection, power loss during erase/body/marker/readback, and two consecutive slot rollovers. Assert at least the previous record loads after every cut.

- [ ] **Step 2: Run checkpoint tests and confirm RED**

```powershell
python tools/tests/test_fota_checkpoint_powercut.py
python tools/tests/test_fota_resume.py
python tools/tests/test_ext_flash_layout.py
```

Expected: missing dual-slot API or old single-sector erase assertions fail.

- [ ] **Step 3: Implement the dual-sector journal**

Write body with marker `0xFFFFFFFF`, write the marker last, read back the entire record, then select by wrap-safe sequence. Never erase the currently newest valid slot before the replacement is proven valid.

- [ ] **Step 4: Make candidate-tail recovery rewrite-safe**

Keep checkpoints on 4 KiB candidate boundaries. After loading a checkpoint, schedule erasure from the committed offset through the sector-rounded advertised package length before requesting the Range tail, so bytes written after a torn checkpoint cannot violate NOR 1-to-0 rules. Do not erase the unused remainder of the 448 KiB candidate partition.

- [ ] **Step 5: Integrate the module and remove the single-slot implementation**

Move the persisted record definition and selection logic out of `fota.c`; retain URL, expected length, version, ETag, and running CRC state needed by the current status API.

- [ ] **Step 6: Run focused tests and confirm GREEN**

Run the three commands from Step 2. Expected: all pass.

---

### Task 5: Implement Authenticated Boot And Six-Hour OTA Checks

**Files:**
- Modify: `include/fota.h`
- Modify: `src/fota.c`
- Modify: `src/main.c`
- Modify: `src/work_mode_sleep.c`
- Modify: `src/at_config.c`
- Create: `tools/tests/test_fota_platform_flow.py`
- Modify: `tools/tests/test_fota_resume.py`
- Modify: `tools/tests/test_fota_package.py`
- Modify: `tools/tests/test_work_mode_contract.py`

**Interfaces:**
- Consumes: `FW_VERSION_COUNTER`, `terminal_identity_sync()`, `cfg_get()->fota_url`, and `cfg_get()->device_api_key`.
- Consumes: `fota_check_parse()` and the dual-slot checkpoint API.
- Produces: check and candidate-preparation states in `fota_state_t` and `bool fota_request_check(void)` for FKEY-triggered rearming.

- [ ] **Step 1: Add a host replay test for the complete state machine**

Stub EC800M open/send/close/state, tick, identity, Flash, reset, and service workspace. Cover: missing key gate, modem-not-ready gate, boot check, exact URL encoding, exact `X-Device-Key`, no-update, newer update, same/older version rejection, cross-host URL rejection, six-hour wrap-safe deadline, three bounded transport retries, HTTP delimiter split across every byte, coalesced header/body, oversized header/body, missing length, chunked, 401, 500, close-before-body, and no secret in captured debug logs.

- [ ] **Step 2: Run the flow test and confirm RED**

Run `python tools/tests/test_fota_platform_flow.py`.

Expected: failures for absent check states/API and unauthenticated request text.

- [ ] **Step 3: Add bounded HTTP operation state**

Use one operation discriminator (`CHECK` or `DOWNLOAD`), `uint16_t` header/body counters, fixed deadlines, and channel-1 ownership. Assemble delimiter fragments safely in the shared workspace; check bodies must fit the fixed parser budget, while download bytes stream directly to external Flash.

- [ ] **Step 4: Prepare candidate Flash incrementally**

Add a preparation state that erases at most one 4 KiB sector per `fota_process()` call, feeds the watchdog before and after the erase, and returns to the main loop between sectors. For a new package erase `[candidate_base, round_up(size, 4096))`; for resume erase only `[checkpoint_offset, round_up(size, 4096))`. Open the HTTP download only after preparation completes.

- [ ] **Step 5: Implement boot and periodic scheduling**

Arm at `fota_init()`, start only when modem and canonical identity are ready and no trial BCR update is pending, set the next deadline to `now + 21600000UL` after each terminal check result, and rearm immediately after successful FKEY configuration.

- [ ] **Step 6: Add authenticated check and download requests**

Generate requests with bounded `snprintf()` and fail closed on truncation:

```http
GET /api/device/updates/check?deviceId=12345678901&deviceModel=A300-406&currentVersionCode=3001 HTTP/1.1
Host: fota.lhhn.net
X-Device-Key: <configured-value>
Connection: close
```

Every initial and resumed download request carries the same header. Never print the request buffer.

- [ ] **Step 7: Bind response metadata to final verification**

Require total bytes to equal advertised `size`, manifest `version_counter` to equal advertised `versionCode`, and all current manifest checks to pass before `fota_bcr_commit_pending()`.

- [ ] **Step 8: Reset immediately after durable pending commit**

Release the external Flash owner and shared workspace, close channel 1, feed the watchdog, then call `NVIC_SystemReset()` directly from the verified completion path. No ACC or motion condition is consulted.

- [ ] **Step 9: Keep low power blocked for every active OTA phase**

Treat check connect/check receive, candidate preparation, download connect/download, verify, and ready-to-reset as active in `work_mode_sleep.c` and `tcp_manager.c`.

- [ ] **Step 10: Run focused tests and confirm GREEN**

```powershell
python tools/tests/test_fota_platform_flow.py
python tools/tests/test_fota_resume.py
python tools/tests/test_fota_package.py
python tools/tests/test_work_mode_contract.py
```

Expected: all pass.

---

### Task 6: Make Bootloader Installation Page-Transactional

**Files:**
- Modify: `bootloader/include/bootloader_config.h`
- Modify: `bootloader/src/image_install.c`
- Modify: `bootloader/host_model.py`
- Create: `tools/tests/test_bootloader_powercut.py`
- Modify: `tools/tests/test_bootloader_platform_contract.py`

**Interfaces:**
- Produces: `BOOTLOADER_INTERNAL_PAGE_SIZE = 2048UL` and retains `BOOTLOADER_COPY_CHUNK_SIZE = 256UL`.
- Invariant: `transaction_offset` is zero, an internal page boundary, or exactly `transaction_length`.
- Invariant: BCR advances only after the complete page is read back and matched.

- [ ] **Step 1: Write exhaustive modeled power-cut tests**

For every app page, inject reset before/after page erase, each 256-byte program, each readback, BCR slot erase, BCR body write, and marker write. Reboot repeatedly and assert convergence to a byte-exact new image without jumping during `BCR_PENDING`.

- [ ] **Step 2: Add C source-contract tests and confirm RED**

Require page-aligned offsets, one page erase per transaction, chunked copy within that page, page readback before BCR commit, and `install_candidate()` routing through `install_resume(0)`.

Run:

```powershell
python tools/tests/test_bootloader_powercut.py
python tools/tests/test_bootloader_platform_contract.py
```

Expected: failures because the current implementation advances every 256 bytes after a whole-app erase.

- [ ] **Step 3: Implement page-granular resume**

For each page beginning at committed `transaction_offset`: erase only that page, program it in 256-byte chunks, read and compare every programmed chunk, then commit the next page boundary or final image length. A reset repeats the entire uncommitted page.

- [ ] **Step 4: Route all candidate installs through the resumable path**

`install_candidate()` verifies and commits the initial pending record, then calls `install_resume(0U)`; remove the separate nonjournaled whole-image copy path for candidates. Keep `copy_image()` only for verified LKG/factory restore.

- [ ] **Step 5: Validate LKG/factory and invalid-vector behavior**

Retain signature verification before restore, LKG-first/factory-second order, watchdog-serviced recovery, and the rule that `boot_jump_to()` rejects invalid MSP/reset vectors.

- [ ] **Step 6: Run focused tests and confirm GREEN**

Run the two commands from Step 2. Expected: exhaustive model and source-contract tests pass.

---

### Task 7: Make The Platform Accept Only Signed N32L406 Packages

**Files:**
- Modify: `backend/src/main/java/com/a300/fota/config/FotaProperties.java`
- Modify: `backend/src/main/java/com/a300/fota/service/CryptoService.java`
- Modify: `backend/src/main/java/com/a300/fota/service/OtaImageMetadata.java`
- Modify: `backend/src/main/java/com/a300/fota/service/OtaImageParser.java`
- Modify: `backend/src/main/java/com/a300/fota/service/FirmwareService.java`
- Modify: `backend/src/main/java/com/a300/fota/domain/FirmwareRelease.java`
- Modify: `backend/src/main/java/com/a300/fota/dto/FirmwareResponse.java`
- Modify: `backend/src/main/resources/application-dev.yml`
- Modify: `backend/src/main/resources/application-prod.yml`
- Test: `backend/src/test/java/com/a300/fota/OtaImageParserTest.java`
- Test: `backend/src/test/java/com/a300/fota/FotaApiSmokeTest.java`

**Interfaces:**
- Produces:

```java
public record OtaImageMetadata(
    long magic, long productId, long hardwareId, long targetAddress,
    long imageLength, long versionCode, long manifestCrc32,
    String payloadSha256, String rawSignatureHex, long totalSize) {}
```

- Consumes: `fota.release-public-key` path to an ECDSA secp256r1 X.509 PEM public key.
- Constants: magic `0x4133464D`, product `0x41333030`, hardware `0x00343036`, target `0x08006000`, manifest size `124`, maximum payload `106496`.

- [ ] **Step 1: Replace legacy parser fixtures with signed-manifest fixtures**

Generate an ephemeral P-256 key pair in the test process, write only its public key to the test temporary directory, and build packages using little-endian `<6I32s64sI`; sign SHA-256 of big-endian `>6I32s`. Cover every identity/bounds/CRC/hash/signature/version failure independently. No private-key file is added to the repository.

- [ ] **Step 2: Run parser and API tests and confirm RED**

From `fota-platform/backend` run:

```powershell
mvn -Dtest=OtaImageParserTest,FotaApiSmokeTest test
```

Expected: the legacy 32-byte parser rejects the new fixture or exposes old metadata.

- [ ] **Step 3: Implement exact manifest parsing**

Use `ByteBuffer.order(LITTLE_ENDIAN)`, compare total length as `124 + imageLength`, compute manifest CRC over exactly the first 120 bytes, and compare payload SHA-256 in constant time.

- [ ] **Step 4: Replace RSA signing with configured ECDSA verification**

Load only the configured public key, require `EC`/`secp256r1`, convert raw `r||s` to a canonical DER sequence, and verify with `NONEwithECDSA` against the already-computed 32-byte canonical digest. Do not create or store a private key.

- [ ] **Step 5: Persist approved manifest metadata without schema destruction**

Map `body_size=imageLength`, `body_crc32=manifestCrc32`, `sha256=payloadSha256`, and `signature=rawSignatureHex`. Compare same-version uploads by the full stored package digest computed transiently or by byte comparison; do not confuse payload SHA with full-package identity.

- [ ] **Step 6: Reject legacy releases during new assignment**

Reparse the stored bytes in `requireAssignableFirmware()` before task creation. Existing records remain queryable, but a legacy package produces a clear validation error and no task.

- [ ] **Step 7: Run focused tests and confirm GREEN**

Run the Maven command from Step 2. Expected: both classes pass.

---

### Task 8: Enforce Device Authentication And Preserve Resume Tasks

**Files:**
- Modify: `backend/src/main/java/com/a300/fota/security/DeviceApiKeyFilter.java`
- Modify: `backend/src/main/java/com/a300/fota/dto/CheckUpdateResponse.java`
- Modify: `backend/src/main/java/com/a300/fota/service/OtaTaskService.java`
- Modify: `backend/src/main/java/com/a300/fota/web/DeviceUpdateController.java`
- Modify: `backend/src/test/java/com/a300/fota/DevicePullContractIT.java`
- Modify: `backend/src/test/java/com/a300/fota/FotaApiSmokeTest.java`

**Interfaces:**
- Check success fields: `updateAvailable`, `versionCode`, `downloadUrl`, `size`.
- Device authentication header: `X-Device-Key` on check and every download/Range request.
- Task terminal transitions: only new-version check-in, explicit failure handling already proven by an authenticated source, or operator cancellation; HTTP response creation is not a completion signal.

- [ ] **Step 1: Add failing authentication tests**

At the real-socket layer, assert `401` for missing/wrong keys and success for the injected test key on check, full download, and Range download. Assert the response body and logs never echo the key.

- [ ] **Step 2: Add failing disconnect/resume tests**

Read only a prefix of a 200/206 response and close the socket. Repeat old-version checks more than three times, then assert the same task URL still returns the requested Range and the task is not `ROLLED_BACK`, `FAILED`, or `GONE`.

- [ ] **Step 3: Run the focused integration tests and confirm RED**

From `fota-platform/backend` run:

```powershell
mvn -Dtest=FotaApiSmokeTest -Dit.test=DevicePullContractIT verify
```

Expected: unauthenticated requests currently succeed and served responses currently transition the task to `DOWNLOADED`/eventual rollback.

- [ ] **Step 4: Require the API key for both device routes**

Remove both contract exemptions from `shouldNotFilter()`. Retain constant-time comparison, `503` for missing server configuration, and the non-device/admin filter behavior.

- [ ] **Step 5: Simplify the check response**

Remove legacy `crc32`; return the exact four-field available response and the one-field no-update response, both with explicit `Content-Length`, JSON content type, and `Connection: close`.

- [ ] **Step 6: Remove false download completion inference**

Delete controller calls that mark completion before delivery and remove old-version install-attempt termination. `authorizeDownload()` records attempts/starting offsets for observability but always permits a nonterminal assigned task.

- [ ] **Step 7: Run focused integration tests and confirm GREEN**

Run the Maven command from Step 3. Expected: smoke and real-socket tests pass.

---

### Task 9: Update The Operator UI And Contract Documentation

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/App.vue`
- Modify: `README.md`
- Modify: `A300-设备主动HTTP-OTA契约.md`
- Modify: `backend/src/main/java/com/a300/fota/dto/SystemConfigResponse.java`
- Modify: `backend/src/main/java/com/a300/fota/web/AdminConfigController.java`

**Interfaces:**
- UI exposes `manifestCrc32`, `manifestCrc32Hex`, payload SHA-256, and signed N32L406 package wording.
- Documentation exposes no actual device key or private-key material.

- [ ] **Step 1: Update frontend types and labels**

Replace `bodyCrc32` naming, legacy magic `0xA300B007`, 32-byte header, 224 KiB claims, and automatic rollback inference text with the 124-byte signed Manifest, 106496-byte App limit, authenticated Range behavior, and nonterminal resume behavior.

- [ ] **Step 2: Update the platform contract**

Document exact request headers, JSON fields, package byte order, signature digest, stable task behavior, six-hour scheduling, immediate reset, page-level Bootloader recovery, and required factory-image HIL acceptance.

- [ ] **Step 3: Build the frontend**

From `fota-platform/frontend` run `npm run build`. Expected: TypeScript and Vite build pass.

- [ ] **Step 4: Scan documentation and UI for stale protocol claims**

Run from `fota-platform`:

```powershell
rg -n "A300B007|32 字节|224 KiB|免密钥|不带任何自定义|bodyCrc32|正文 CRC32|0x8108|8800" README.md A300-设备主动HTTP-OTA契约.md backend/src/main frontend/src
```

Expected: no active old-contract claims; historical compatibility comments must be explicitly labeled and cannot affect device routes.

---

### Task 10: Run Full Regression And Release Gates

**Files:**
- Modify tests only when a failure demonstrates an intended OTA contract update; do not weaken unrelated guards.
- Inspect: all changed files in both target directories.

**Interfaces:**
- Produces: fresh automated evidence and a separate HIL checklist; does not flash or deploy.

- [ ] **Step 1: Run all firmware host tests**

From `A300-first` run every `tools/tests/test_*.py` script using the repository's established test runner or a PowerShell loop that stops on the first nonzero exit. Expected: every test passes; record the exact count.

- [ ] **Step 2: Build application and Bootloader**

```powershell
make all
make -C bootloader all
make release-guard
make ram-guard
```

Expected: both ARM images link, release guard passes, and App/Bootloader RAM remain within the 24 KiB budget.

- [ ] **Step 3: Run full platform backend verification**

From `fota-platform/backend` run `mvn verify`. Expected: unit and Failsafe integration tests pass, including the real TCP contract.

- [ ] **Step 4: Run the frontend production build**

From `fota-platform/frontend` run `npm run build`. Expected: pass.

- [ ] **Step 5: Render deployment configuration without starting services**

From `fota-platform`, if Docker and the required ignored environment file are available, run:

```powershell
docker compose --env-file .env.prod -f docker-compose.enterprise.yml config --quiet
```

Expected: exit code 0. Do not run `up`, restart containers, or expose ports.

- [ ] **Step 6: Inspect final scope and whitespace**

From `A300-first`, run `git diff --check` and inspect `git status --short` plus the scoped diff. For `fota-platform`, list timestamps/paths of files touched in this work and inspect their content because it is not currently recognized as a Git worktree. Confirm there are no secrets, private keys, generated production data, debug bypasses, or N32G452 inputs.

- [ ] **Step 7: Produce the HIL acceptance checklist**

Require real-device evidence for: keyed check, fragmented response, disconnect and MCU reset at multiple download offsets, stable Range resume, power loss during external checkpoint commit, immediate reset after verification, power loss during multiple internal Flash pages, offline install continuation, three failed trial boots, LKG restore, factory restore, and cryptographic readback of the factory partition. Mark the feature “needs real-device/HIL verification” until all are observed.

- [ ] **Step 8: Report results without committing or deploying**

List changed files, protocol/behavior changes, exact commands and outcomes, unexecuted HIL/deployment checks, and residual risks. Do not create a Git commit unless the user separately authorizes it.
