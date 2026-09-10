# A300-Compatible OTA Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Make N32L406 use the active A300 OTA operating model: upload a normal 32-byte-header `.bin`, sign it on the platform, return detached verification metadata, download with resume, verify, reboot immediately, and verify/install again in Bootloader.

**Architecture:** Keep the N32L406 memory map and recovery stores, but replace the embedded 124-byte signed manifest with the active A300 32-byte firmware header. The platform owns the release private key and signs SHA-256(header + body); App persists detached signature/key-id/package hash in a committed OTA authorization record; Bootloader reads that record, verifies the package and installs body bytes from offset 32.

**Tech Stack:** C99/N32L40x, Python release tools, Spring Boot 3/Java 17, Vue 3/TypeScript.

## Global Constraints

- Header is exactly little-endian `<IIIII12s>`: magic `0xA300B007`, version, body size, body CRC32, product `0x41333030`, 12 zero bytes.
- N32L406 App target remains `0x08006000`; body maximum remains `106496` bytes.
- Signature is ECDSA P-256 raw `r||s`, exactly 64 bytes, over SHA-256 of the complete 32-byte-header package.
- Platform private key is supplied by an external path/environment configuration and is never committed, logged, or returned.
- Device check remains HTTP/1.1 with `X-Device-Key`; download remains authenticated and Range-capable.
- Detached SHA-256, signature and key-id must survive power loss before BCR becomes Pending.
- Signature verification success commits Pending and triggers immediate reset; no status-report delay may block reset.
- Bootloader verifies header, bounds, body CRC32, complete-package SHA-256 and detached signature before erasing App.
- Existing page-transaction install, Trial, LKG, Factory, rollback, watchdog and SWD-first-boot behavior remain intact.
- No commit, deployment, service restart, device command or flashing is authorized.

---

### Task 1: Shared Firmware Package And Persistent Authorization

**Files:** Modify `include/fota.h`, `include/fota_checkpoint.h`, `src/fota.c`, `src/fota_checkpoint.c`, `bootloader/include/boot_contract.h`, `bootloader/include/image_verify.h`, `bootloader/src/image_verify.c`, `bootloader/src/image_install.c`; test `tools/tests/test_fota_package.py`, `tools/tests/test_fota_checkpoint_powercut.py`, `tools/tests/test_bootloader_powercut.py`, `tools/tests/test_bootloader_bcr_failclosed.py`.

- [ ] Add failing host tests for the 32-byte header, detached metadata persistence, corrupt signature/hash/header rejection, `+32` install offset, and reset immediately after Pending commit.
- [ ] Run the focused tests and record the expected failures.
- [ ] Implement the shared header and committed authorization record using an unused external-flash sector with magic/version/length/generation/CRC/commit marker.
- [ ] Update App download verification and Bootloader verification/install without weakening rollback or power-cut recovery.
- [ ] Run focused tests, Bootloader build, map guard and internal flash layout tests.

### Task 2: Platform-Side Signing And Device Contract

**Files:** Modify `fota-platform/backend/src/main/java/com/a300/fota/config/FotaSecurityProperties.java`, `service/CryptoService.java`, `service/OtaImageParser.java`, `service/FirmwareService.java`, `service/OtaTaskService.java`, `dto/CheckUpdateResponse.java`, configuration examples; update related backend tests.

- [ ] Add failing tests requiring a valid 32-byte-header `.bin`, platform P-256 signing, raw signature persistence, check response metadata, key mismatch rejection and Range identity.
- [ ] Run focused Maven tests and record expected failures.
- [ ] Load the private key only from configured external path, derive/check its public key and sign SHA-256(package).
- [ ] Store package hash/signature/key-id atomically with publication and return them only for assigned devices.
- [ ] Run `mvn test` and `mvn verify`.

### Task 3: Release Tool And Operator UI

**Files:** Modify `A300-first/tools/build_dev_release.py`, add/update package generator tests; modify `fota-platform/frontend/src/App.vue`, `api.ts`, `types.ts` only as required.

- [ ] Add failing tests that release output is `App-...-OTA.bin` with the exact 32-byte header and no embedded signature.
- [ ] Change release output and manifest while retaining App/Bootloader/Combined SWD artifacts.
- [ ] Update UI copy/accept filters to upload the normal OTA `.bin`; do not expose signing key controls.
- [ ] Run Python release tests and `npm run build`.

### Task 4: Cross-Component Verification And Test Artifacts

**Files:** Add/update protocol fixture tests in both repositories; generate a new immutable `dist/dev-key/<timestamp>` directory.

- [ ] Generate one package fixture and prove byte-for-byte agreement across Python, Java, App C and Bootloader C.
- [ ] Verify interrupted download/resume, reset after verification, interrupted install/resume, Trial confirmation and rollback.
- [ ] Rebuild App and Bootloader; verify vectors, addresses, hashes and size guards.
- [ ] Run `git diff --check`, inspect scoped diffs, and document tests requiring real hardware/HIL.
