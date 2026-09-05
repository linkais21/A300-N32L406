# N32L406CBL7 Final Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the N32L406CBL7 migration, close the two confirmed blind-zone progress defects, and generate traceable Bootloader and App artifacts signed with a local ECDSA P-256 development key.

**Architecture:** Preserve the existing native N32L406 application and external-Flash layout while moving the App to `0x08006000`, adding a real fail-closed Bootloader platform, and sharing one manifest/signature contract between Bootloader, App, and host packaging. Keep blind-zone repair and STOP2/reset work as independently testable tasks before the final integrated build and artifact gate.

**Tech Stack:** C99, ARM Cortex-M4, Nations N32L40x SPL 2.2.0, ARM GNU Toolchain 14.3, BY25Q16ESMIG SPI NOR, ECDSA P-256, SHA-256, Python 3 host tests and packaging tools, GNU Make-compatible build.

## Global Constraints

- Target is exactly N32L406CBL7 at 64 MHz, with 128 KiB internal Flash and 24 KiB SRAM; `N32L406CDL7 / 384 KiB` is historical and must not enter build metadata or limits.
- Bootloader is exactly 24 KiB at `0x08000000–0x08005FFF`; App is at most 104 KiB at `0x08006000–0x0801FFFF`.
- External BY25Q16ESMIG partitions and `ext_flash_store` owner arbitration remain unchanged.
- Bootloader and App verify ECDSA P-256 signatures using one embedded public key; no SHA-only fallback, private-key firmware code, or simplified home-grown verifier is allowed.
- The development private key stays only under ignored `.keys/`; every generated firmware/package artifact is marked `DEV-KEY` and is not production-ready.
- Bootloader preserves a previously verified signed package as LKG; it never creates an LKG signature.
- Static allocation, bounded copying, bounded retries, watchdog service, NOR 1→0 programming, sector erase, read-back and fail-closed behavior are mandatory.
- Preserve all existing user-owned dirty changes. Record the pre-task diff for overlapping files and edit only required hunks.
- Do not import N32G452 startup, linker, clock, interrupt, SDK or peripheral code.
- Do not commit, push, flash hardware or deploy unless the user separately authorizes that action. Each task ends with a scoped diff/review checkpoint instead of a Git commit.

---

### Task 1: Close the two blind-zone no-progress loops

**Files:**
- Modify: `tools/tests/test_blind_zone_store.py`
- Modify: `src/blind_zone.c`
- Review only unless an interface change is proven necessary: `include/blind_zone.h`
- Update evidence: `docs/blind-zone-fix-round-3-rereview.md`

**Interfaces:**
- Consumes: existing scratch repair state, `BZ_SLOT_PREPARED`, `BZ_SLOT_ACTIVE`, ring head/tail and reconcile state.
- Produces: bounded repair verification accepting the state that was backed up, plus an idempotent stale-next-slot reclamation transition that advances or terminates on every call.

- [ ] **Step 1: Capture the protected diff and focused baseline**

Run:

```powershell
git diff -- include/blind_zone.h src/blind_zone.c tools/tests/test_blind_zone_store.py
python tools/tests/test_blind_zone_store.py
```

Save the existing diff in the task log. Expected baseline is either the two named cases failing/hanging or an existing test passing without proving a bounded progress count; do not edit until the exact transition path is identified.

- [ ] **Step 2: Strengthen the PREPARED repair regression to prove bounded completion**

In the existing repair test that forces a PREPARED slot through scratch backup/restore, add a fixed call budget and assert all of the following: the repair state returns to idle within that budget, the record still classifies as PREPARED before commit, the next append/reconcile call can commit it to ACTIVE, and reboot recovery retains it once. Run:

```powershell
python tools/tests/test_blind_zone_store.py
```

Expected RED: the state remains in verification because restored PREPARED is rejected as not ACTIVE, or the call budget expires.

- [ ] **Step 3: Fix repair verification using the recorded expected slot state**

Change the repair verification branch in `src/blind_zone.c` so the post-restore record must match the state captured for the victim: PREPARED repair accepts a valid PREPARED record with identical sequence/payload/CRC; ACTIVE repair still requires ACTIVE. Do not accept corrupt, erased, or unrelated records and do not weaken payload equality.

Run the focused test. Expected GREEN: completion inside the fixed budget with the PREPARED→ACTIVE transition still requiring the normal final commit marker.

- [ ] **Step 4: Strengthen the full-ring stale ACTIVE regression**

Extend the existing full-ring setup so `next slot` contains stale ACTIVE sequence 1 while the logical FIFO has wrapped. Repeatedly call the real reconcile/recovery function with a fixed budget and assert one of the valid progress outcomes on every state transition: reclaim the obsolete sector/slot, advance the physical cursor, or finish reconcile. Assert the same stale address is not selected indefinitely, FIFO order remains unchanged, and a new append succeeds after reboot.

Run the focused test. Expected RED: the budget expires while reconcile repeatedly selects the same stale ACTIVE slot.

- [ ] **Step 5: Add the minimal idempotent stale-slot reclamation transition**

In the full-ring `next slot` branch, classify an ACTIVE/PREPARED record as stale only when its sequence is outside the live FIFO interval using the existing wrap-safe sequence comparison. Route it through the existing scratch-backed sector reclamation path, persist the cursor/head transition before retrying, and make a repeated call after any power cut resume from the persisted phase rather than reselecting the original slot.

Run:

```powershell
python tools/tests/test_blind_zone_store.py
python tools/tests/test_blind_zone_replay.py
python tools/tests/test_ext_flash_store_host.py
python tools/tests/test_ext_flash_layout.py
git diff --check
```

Expected: all PASS, no unbounded retry, and no external-Flash layout change.

- [ ] **Step 6: Record the Fix Round 3 evidence checkpoint**

Update `docs/blind-zone-fix-round-3-rereview.md` with the exact RED symptom, GREEN commands, call budgets and remaining HIL requirement. Review the scoped diff and confirm pre-existing unrelated hunks are byte-for-byte preserved.

### Task 2: Freeze N32L406CBL7 memory map and App vector relocation

**Files:**
- Create: `include/firmware_layout.h`
- Modify: `ldscript/n32l406.ld`
- Modify: `bootloader/ldscript/n32l406_boot.ld`
- Modify: `bootloader/include/bootloader_config.h`
- Modify: `src/main.c`
- Modify: `Makefile`
- Modify: `bootloader/Makefile`
- Modify: `tools/map_ram_guard.py`
- Create: `tools/tests/test_internal_flash_layout.py`
- Modify: `tools/tests/test_ram_guard.py`
- Modify: `tools/release_guard.py`
- Modify: root `AGENTS.md` only for the stale MCU capacity lines under `A300-first` rules

**Interfaces:**
- Produces: `FW_FLASH_BASE`, `FW_FLASH_END`, `BOOT_FLASH_BASE`, `BOOT_FLASH_SIZE`, `APP_FLASH_BASE`, `APP_FLASH_SIZE`, `SRAM_BASE`, and `SRAM_SIZE` in `firmware_layout.h`.
- Consumes: linker MEMORY regions, Bootloader image bounds, VTOR initialization and map guards.

- [ ] **Step 1: Write a RED source/linker layout test**

Create `tools/tests/test_internal_flash_layout.py` to parse the shared layout header and both linker scripts. Assert exact values: Bootloader origin `0x08000000`, length `24K`; App origin `0x08006000`, length `104K`; RAM origin `0x20000000`, length `24K`; both end at their frozen exclusive bounds; no overlap; Bootloader release maximum is 24 KiB; App source contains an early VTOR relocation to `APP_FLASH_BASE` before `hw_nvic_init()`.

Run:

```powershell
python tools/tests/test_internal_flash_layout.py
```

Expected RED: current App origin is `0x08000000`, Bootloader length is 12K, old release max is 11K, and VTOR relocation is absent.

- [ ] **Step 2: Add one shared C layout contract and correct both linkers**

Define the constants in `include/firmware_layout.h`. Include it from `bootloader_config.h` rather than duplicating address arithmetic. Change Bootloader FLASH to 24K with a `<= 0x6000` ASSERT. Change App FLASH origin to `0x08006000`, length to 104K, retain 24K RAM, and add a link-time ASSERT that the App load image ends at or before `0x08020000`.

- [ ] **Step 3: Relocate VTOR before enabling application interrupts**

At the start of App `main()`, before `hw_nvic_init()` and peripheral interrupt enabling, call:

```c
NVIC_SetVectorTable(NVIC_VectTab_FLASH, APP_FLASH_BASE - FW_FLASH_BASE);
```

Include `firmware_layout.h` and the SPL declaration. Keep the startup vector section at the beginning of App FLASH.

- [ ] **Step 4: Update build identity and capacity guards**

Replace target comments/guards that describe `N32L406CDL7 / 384 KiB` with `N32L406CBL7 / 128 KiB / 24 KiB SRAM`. Extend `map_ram_guard.py` to accept App and Bootloader modes and reject App Flash over 106496 bytes, Bootloader Flash over 24576 bytes, or static SRAM over 20480 bytes. Extend unit tests with just-below, exact-limit and one-byte-over cases for all three limits.

Run:

```powershell
python tools/tests/test_internal_flash_layout.py
python tools/tests/test_ram_guard.py
python tools/release_guard.py
```

Expected: all PASS and no stale release-controlled MCU capacity value.

- [ ] **Step 5: Build the address-only baseline**

Use the configured ARM GNU 14.3 executables and a GNU Make-compatible command. Build App and the current fail-closed Bootloader, then inspect ELF headers and symbols:

```powershell
make all
make ram-guard
make -C bootloader all
```

Expected: App `.isr_vector` begins at `0x08006000`; Bootloader begins at `0x08000000`; neither exceeds its region. Existing Bootloader unresolved platform functionality is not considered complete in this task.

### Task 3: Define one canonical signed-package contract and development key flow

**Files:**
- Modify: `.gitignore`
- Modify: `bootloader/include/image_manifest.h`
- Modify: `bootloader/include/image_verify.h`
- Modify: `bootloader/src/image_verify.c`
- Create: `include/trusted_public_key.h`
- Create: `tools/dev_key.py`
- Create: `tools/sign_firmware.py`
- Create: `tools/tests/test_dev_signed_package.py`
- Modify: `tools/tests/test_image_manifest.py`
- Modify: `tools/tests/test_fota_package.py`

**Interfaces:**
- Produces: `void image_signature_digest(const image_manifest_t *manifest, uint8_t out[32]);`, hashing the canonical big-endian tuple `{magic, product_id, hardware_id, target_address, image_length, version_counter, payload_sha256}`.
- Produces: raw 64-byte signature `r || s`, each unsigned 32-byte big-endian value.
- Produces: `.keys/dev-p256-private.pem`, ignored and local-only; `include/trusted_public_key.h` containing the 64-byte uncompressed affine `X || Y` public key and `TRUSTED_KEY_LABEL "DEV-KEY"`.
- Produces: signed package wire layout `[124-byte image_manifest_t][payload]`.

- [ ] **Step 1: Write package and tamper RED tests**

Create a Python test using installed `cryptography` P-256 support. It must generate a temporary key, call the real signing tool, parse the 124-byte manifest, verify the canonical digest and raw signature, and reject independently mutated payload, product ID, hardware ID, target address, length, version counter, SHA and signature. Assert a version below the supplied rollback floor is rejected.

Run:

```powershell
python tools/tests/test_dev_signed_package.py
```

Expected RED because the key/signing tools and canonical digest contract do not exist.

- [ ] **Step 2: Implement deterministic manifest serialization and signing**

Implement `tools/sign_firmware.py` with explicit little-endian manifest field packing matching the C packed struct, canonical big-endian signature-digest input, SHA-256 payload hashing, DER-to-raw ECDSA conversion, manifest CRC32 with `crc32` excluded/zeroed exactly as firmware expects, and bounds checks for product `0x41333030`, hardware `0x00343036`, target `0x08006000`, payload `1..106496`, and positive 32-bit version counter. Output filenames must contain `N32L406CBL7-DEV-KEY`.

- [ ] **Step 3: Generate the ignored local development key and public header**

Add `.keys/` to `.gitignore`. `tools/dev_key.py` creates the key only when absent, refuses to overwrite an existing private key, validates it is `SECP256R1`, and regenerates only the public header from an existing private key when requested. Run it once locally and verify:

```powershell
python tools/dev_key.py --key .keys/dev-p256-private.pem --public-header include/trusted_public_key.h
git status --short --ignored .keys include/trusted_public_key.h
```

Expected: private key is ignored; only the public header is visible as source; command output contains no private scalar or PEM body.

- [ ] **Step 4: Make firmware compute and verify the same canonical digest**

Add `image_signature_digest()` beside the existing SHA-256 implementation and make candidate/internal package verification pass its output—not the payload hash alone—to the ECDSA verifier. Remove `boot_ecdsa_sign` from the public API and all call sites. Retain payload SHA comparison, manifest CRC, target/ID/bounds and rollback checks as independent prerequisites.

Run:

```powershell
python tools/tests/test_dev_signed_package.py
python tools/tests/test_image_manifest.py
python tools/tests/test_fota_package.py
git diff --check
```

Expected: all PASS; mutations fail at the appropriate validation layer.

### Task 4: Add an audited software P-256 verifier shared by Bootloader and App

**Files:**
- Vendor: `third_party/micro-ecc/uECC.c`
- Vendor: `third_party/micro-ecc/uECC.h`
- Vendor: `third_party/micro-ecc/LICENSE.txt`
- Create: `include/firmware_signature.h`
- Create: `src/firmware_signature.c`
- Modify: `bootloader/Makefile`
- Modify: root `Makefile`
- Modify: `bootloader/src/image_verify.c`
- Modify: `src/fota.c`
- Create: `tools/tests/test_firmware_signature.py`

**Interfaces:**
- Produces: `bool firmware_signature_verify(const uint8_t digest[32], const uint8_t signature[64]);` using `uECC_secp256r1()` and embedded `trusted_public_key`.
- Replaces: fail-closed weak `boot_ecdsa_verify()` and `fota_ecdsa_verify()` defaults with one real implementation.

- [ ] **Step 1: Acquire and pin the verifier source with license evidence**

Use the upstream micro-ecc release source without local arithmetic changes. Record the upstream version/commit and SHA-256 of `uECC.c`, `uECC.h`, and license in `third_party/micro-ecc/README-A300.md`. Configure only secp256r1 and verification; disable signing, RNG and unused curves. If the source cannot be obtained and verified, stop this task as blocked rather than substituting an unreviewed ECC implementation.

- [ ] **Step 2: Write a RED host C verifier harness**

Generate fixed P-256 vectors in Python and compile the real `firmware_signature.c`, generated public header and vendored verifier with host GCC. Assert valid signature true; bit flips in digest, r, s or public key false; zero/out-of-range r or s false; wrong key false.

Run:

```powershell
python tools/tests/test_firmware_signature.py
```

Expected RED until the real verifier wrapper is present.

- [ ] **Step 3: Implement the shared wrapper and wire both consumers**

Validate non-null input and scalar range through the library, then call `uECC_verify(trusted_public_key, digest, 32, signature, uECC_secp256r1())`. Compile the exact same wrapper/library into App and Bootloader. Remove or rename weak hooks so the linker cannot silently select a false stub in production builds.

- [ ] **Step 4: Verify cryptographic behavior and size**

Run:

```powershell
python tools/tests/test_firmware_signature.py
python tools/tests/test_dev_signed_package.py
python tools/tests/test_fota_package.py
make all
make -C bootloader all
```

Expected: valid package accepted, all tamper vectors rejected, both link maps contain `firmware_signature_verify` and `uECC_verify`, Bootloader remains within 24 KiB and App within 104 KiB.

### Task 5: Implement the N32L406 Bootloader platform and safe LKG transaction

**Files:**
- Create: `bootloader/include/platform_n32l406.h`
- Create: `bootloader/src/platform_n32l406.c`
- Modify: `bootloader/src/image_install.c`
- Modify: `bootloader/src/image_verify.c`
- Modify: `bootloader/src/bcr.c`
- Modify: `bootloader/src/main.c`
- Modify: `bootloader/Makefile`
- Create: `tools/tests/test_bootloader_platform_contract.py`
- Modify: `tools/tests/test_bcr.py`
- Modify: `tools/tests/test_image_manifest.py`

**Interfaces:**
- Produces: real bounded `boot_ext_read/write/erase/is_complete`, `boot_int_flash_read/erase/program`, `boot_watchdog_feed`, `boot_reset_was_fault_or_watchdog`, `boot_rollback_counter`, `boot_jump_to`, BCR read/write/erase/readback and recovery-step implementations.
- Consumes: SPI1 PA4/PA5/PA6/PA7, N32L406 SPL Flash/IWDG/RCC/CMSIS APIs, shared layout and signature verifier.

- [ ] **Step 1: Write a RED static/platform contract test**

Assert Bootloader Makefile compiles `platform_n32l406.c`, N32L406 SDK clock/GPIO/SPI/Flash/IWDG sources and shared signature sources; release builds have no weak hardware hook definitions; all external/internal Flash functions check overflow-safe bounds; jump validates MSP inside `0x20000000..0x20006000` and reset vector inside `0x08006001..0x08020000`; jump disables IRQ/SysTick, sets VTOR/MSP and branches.

Run `python tools/tests/test_bootloader_platform_contract.py`; expect RED.

- [ ] **Step 2: Implement minimal Bootloader hardware initialization and bounded SPI NOR access**

Initialize HSI/PLL at 64 MHz, PA4 GPIO CS and SPI1 pins/mode compatible with `spi_flash.c`, then implement JEDEC/status polling with a fixed timeout and watchdog reload. Enforce `[0, FLASH_TOTAL_SIZE)` bounds, 256-byte page boundaries, 4 KiB sector erase and read-back. A timeout or status error returns false.

- [ ] **Step 3: Implement internal Flash and safe App jump**

Unlock only around App erase/program, enforce `[APP_FLASH_BASE, APP_FLASH_END)`, use SPL page erase/word program, relock on every exit, and read-back each programmed chunk. Before jump, validate vector words, disable interrupts and SysTick, clear pending NVIC state, set `SCB->VTOR`, load MSP and call the Thumb reset vector. Invalid vectors return to recovery without branching.

- [ ] **Step 4: Implement BCR/reset/rollback hooks**

Map BCR slots to the existing external resume addresses, use sector erase plus record write/read-back/commit-marker ordering, choose the newest wrap-safe valid sequence, and classify IWDG/WWDG/low-power resets from RCC flags before clearing them. Rollback floor is the highest valid installed/healthy signed image version recorded by BCR; it cannot decrease after a trial failure.

- [ ] **Step 5: Remove Bootloader-side LKG signing and preserve signed packages**

Change installation so candidate is fully verified first, then copy `[manifest][payload]` from candidate to LKG with erase/write/read-back and re-verification. Never synthesize a manifest, hash or signature from the internal App. Install order is candidate verify → signed-package LKG preservation → App erase/copy/read-back/hash → BCR Trial commit → jump. Recovery order re-verifies LKG, then Factory, before copying either.

- [ ] **Step 6: Run Bootloader model, contract and ARM build gates**

Run:

```powershell
python tools/tests/test_bootloader_platform_contract.py
python tools/tests/test_bcr.py
python tools/tests/test_image_manifest.py
python tools/tests/test_fota_package.py
make -C bootloader all
```

Expected: all host tests PASS; build has no unresolved hardware/crypto hook; ELF is ≤24576 bytes. Mark external Flash timings, reset flags and actual jump as HIL-required.

### Task 6: Complete App-side FOTA/BCR integration

**Files:**
- Create: `include/boot_contract.h`
- Modify: `bootloader/include/bcr.h`
- Modify: `src/fota.c`
- Modify: `Makefile`
- Modify: `tools/tests/test_fota_package.py`
- Modify: `tools/tests/test_fota_resume.py`
- Modify: `tools/tests/test_bcr.py`

**Interfaces:**
- Produces: shared BCR wire record/state definitions in `boot_contract.h` and `bool fota_bcr_commit_pending(uint32_t version, uint32_t length, uint32_t target)` using the same dual-slot commit contract.
- Consumes: canonical manifest verifier, real App signature verifier, external-Flash owner arbitration and candidate/resume layout.

- [ ] **Step 1: Add RED tests for shared contract and App pending commit**

Assert App rejects a package when canonical signature, target, bounds, version or rollback floor is invalid; successful completed download commits Pending only after package verification; BCR write/erase/readback failure leaves the prior valid BCR selected; repeated completion is idempotent.

Run the three focused tests. Expected RED while weak `fota_bcr_commit_pending` remains.

- [ ] **Step 2: Move wire definitions to one shared header**

Make both App and Bootloader include `boot_contract.h` for exact BCR magic, marker, state values, record layout and slot addresses. Retain `_Static_assert` wire sizes and add compile tests that include the header from both build include paths.

- [ ] **Step 3: Implement App BCR Pending commit and reset request**

Acquire external Flash as OTA owner, load newest valid BCR, create `sequence + 1` Pending record with candidate version/length/`APP_FLASH_BASE`, commit using erase→record→read-back→marker, release owner on all paths, then request a system reset. Never reset if verification or BCR commit fails.

- [ ] **Step 4: Verify App/Bootloader compatibility**

Run:

```powershell
python tools/tests/test_fota_package.py
python tools/tests/test_fota_resume.py
python tools/tests/test_bcr.py
make all
make -C bootloader all
```

Expected: all PASS and both maps reference the same contract values.

### Task 7: Implement STOP2 entry, restoration and reset diagnostics

**Files:**
- Create: `include/reset_diag.h`
- Create: `src/reset_diag.c`
- Modify: `include/power_mgr.h`
- Modify: `src/power_mgr.c`
- Modify: `src/main.c`
- Modify: `include/hw_init.h`
- Modify: `src/hw_init.c`
- Modify: `Makefile`
- Create: `tools/tests/test_power_stop2_contract.py`
- Create: `tools/tests/test_reset_diag.py`

**Interfaces:**
- Produces: `void reset_diag_capture(void);`, `reset_reason_t reset_diag_reason(void);`, `const char *reset_diag_name(reset_reason_t reason);`.
- Produces: `bool hw_restore_after_stop2(void);` and a bounded `pwr_enter_stop2()` path with shallow-sleep fallback.
- Consumes: `PWR_EnterSTOP2Mode(PWR_STOPENTRY_WFI, SRAM1EN_SRAM2EN)`, RCC reset flags, existing hardware initialization primitives and wake ISR flags.

- [ ] **Step 1: Write RED source-level and host classification tests**

Assert deep sleep no longer calls `PWR_EnterSLEEPMode` as STOP; it calls `PWR_EnterSTOP2Mode` with both SRAM banks retained; restoration calls 64 MHz clock recovery before re-enabling SysTick/peripherals; fallback uses shallow sleep only when STOP2 preconditions fail. Compile `reset_diag.c` against fake RCC flags and assert priority/classification for IWDG, WWDG, software, pin, POR and low-power reset, followed by flag clearing.

- [ ] **Step 2: Implement reset capture before RCC flags are cleared elsewhere**

Call `reset_diag_capture()` at the beginning of App main, retain a static enum only, clear RCC flags once captured, and print the bounded reason name after debug UART initialization. Do not log device identifiers or locations.

- [ ] **Step 3: Implement explicit STOP2 preconditions and fallback**

Require no external-Flash owner, no FOTA write/install transaction, no tracked JT808 send, and no pending modem/GNSS critical transaction. If any condition is false, remain in state or use `PWR_EnterSLEEPMode(0, PWR_STOPENTRY_WFI)` as the documented shallow fallback; never log STOP2 entry for fallback.

- [ ] **Step 4: Enter STOP2 and restore the platform in order**

Before WFI, clear pending wake flags and suspend tick-dependent peripherals. Enter STOP2 retaining SRAM1 and SRAM2. On return, call `hw_restore_after_stop2()` to restore HSI/PLL 64 MHz and SystemCoreClock first, then TIM tick/NVIC/GPIO AF/UART/SPI/I2C/ADC and driver-visible peripheral state. Only after restoration succeeds call `enter_active()`; otherwise request a controlled reset.

- [ ] **Step 5: Run focused and regression tests**

Run:

```powershell
python tools/tests/test_power_stop2_contract.py
python tools/tests/test_reset_diag.py
python tools/tests/test_feature_guards.py
make all
```

Expected: all PASS; map remains within App limits. Record RTC/ACC/charge wake, clock accuracy, modem recovery and current draw as HIL-required.

### Task 8: Run full regression and generate DEV-KEY Bootloader/App artifacts

**Files:**
- Create: `tools/build_dev_release.py`
- Create: `tools/tests/test_dev_release_manifest.py`
- Create generated ignored outputs under: `dist/dev-key/`
- Create: `docs/n32l406cbl7-dev-key-build-report.md`
- Modify: `.gitignore` to ignore generated `dist/` content while retaining the report

**Interfaces:**
- Produces: Bootloader ELF/HEX/BIN/map, App ELF/HEX/BIN/map, signed App package, optional combined programming image, and `SHA256SUMS.json`, all named with `N32L406CBL7-DEV-KEY`.
- Consumes: ARM GNU 14.3 toolchain, local `.keys/dev-p256-private.pem`, embedded public key, both Makefiles and all automated gates.

- [ ] **Step 1: Write a RED release-manifest validator**

Assert the JSON manifest contains schema version, `DEV-KEY`, MCU `N32L406CBL7`, exact memory ranges, firmware version/version counter, toolchain version, Git revision and dirty flag, each artifact path/size/SHA-256, App vector MSP/reset-handler validation, and offline signature verification. Reject any artifact filename lacking `DEV-KEY` or any hash mismatch.

- [ ] **Step 2: Implement the bounded build orchestrator**

`tools/build_dev_release.py` invokes the configured compiler/objcopy/size commands without deleting source or user files, places new outputs only under a newly created timestamped `dist/dev-key/<build-id>/`, signs the App BIN, verifies it with the public key, creates a combined image by placing Bootloader at offset 0 and App at offset `0x6000` filled with `0xFF`, validates vectors and boundaries, then writes hashes last. It must fail on warnings, missing key, stale/mismatched public key, build failure, size overflow or signature failure.

- [ ] **Step 3: Run every host test fresh and stop at the first failure**

Run each `tools/tests/test_*.py` in sorted order with `REQUIRE_GCC=1`, recording command, exit code and output. A timeout is a failure to investigate, not a skip. Then run:

```powershell
python tools/release_guard.py
python tools/tests/test_feature_guards.py
git diff --check
```

Expected: all automated tests PASS with no skipped required compiler test.

- [ ] **Step 4: Build and verify final artifacts**

Run:

```powershell
python tools/build_dev_release.py --key .keys/dev-p256-private.pem --output dist/dev-key
python tools/tests/test_dev_release_manifest.py --manifest <generated-SHA256SUMS.json>
```

Expected: fresh App and Bootloader builds; size/address/map guards PASS; signed App package verifies; tamper self-test rejects changes; manifest validator PASS.

- [ ] **Step 5: Review security and worktree boundaries**

Verify `.keys/` is ignored and untracked, no PEM/private scalar appears in tracked files or logs, generated artifacts are ignored, all source edits are in scope, and pre-existing unrelated dirty hunks remain. Record `git status --short`, `git diff --stat`, toolchain version and artifact SHA-256 without staging or committing.

- [ ] **Step 6: Write the final development-build report**

Document automated PASS evidence and link each artifact. Label the result exactly **“N32L406CBL7 DEV-KEY development build complete; not production-ready.”** List as unexecuted external gates: Bootloader vector jump, candidate install and power cuts, Trial/LKG/Factory rollback, STOP2 wake/current tests, watchdog/brownout tests, Zhongkewei vendor/capture validation and 72-hour mixed-load soak.

