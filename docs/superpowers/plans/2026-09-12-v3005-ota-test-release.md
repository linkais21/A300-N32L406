# A300 V3.005 OTA Test Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate an immutable V3.005 firmware and OTA artifact set whose only intentional difference from the current V3.004 source is release identity.

**Architecture:** Keep the current dirty V3.004 working tree as the source baseline. Drive the version bump through `release_identity.json`, regenerate the canonical version header, update version-specific documentation and guard expectations, then use the repository release builder to create and validate `artifacts/V3.005/`.

**Tech Stack:** C99, ARM GNU Toolchain, GNU Make, Python 3 release/test scripts, PowerShell version generator.

## Global Constraints

- Runtime version is `T360-A300_406_20260823000000,V3.005`.
- OTA numeric version counter is `3005`.
- OTA model remains `A300-406`; JT808 model remains `T360-A300`; manufacturer remains `70110`.
- No functional firmware, protocol, configuration, Flash-layout, bootloader, or OTA logic change is permitted.
- Preserve all existing user changes and all V3.003/V3.004 artifacts.
- Do not commit, push, upload, deploy, program hardware, or send device commands.
- Hardware OTA acceptance remains a real-device/HIL verification item.

---

### Task 1: Version contract RED to GREEN

**Files:**
- Modify: `tools/tests/test_release_identity_contract.py`
- Modify: `release_identity.json`
- Modify: `README.md`
- Generated: `include/build_version.h`
- Modify: `tools/release_guard.py`

**Interfaces:**
- Consumes: existing release identity JSON schema and canonical guard normalization.
- Produces: revision `5`, runtime version `V3.005`, and counter `3005` for all build consumers.

- [x] **Step 1: Change the contract-test expected identity to V3.005**

Set `firmware_revision` to `5`, `firmware_version` to
`T360-A300_406_20260823000000,V3.005`, `firmware_version_counter` to `3005`,
and make the negative mismatch fixture use `3006UL`.

- [x] **Step 2: Run the focused test and verify RED**

Run: `python tools/tests/test_release_identity_contract.py`

Expected: FAIL because `release_identity.json` still reports V3.004/3004.

- [x] **Step 3: Apply the minimal release identity and documentation change**

Update `release_identity.json` to revision 5/version V3.005/counter 3005 and
update README current-artifact paths and examples from V3.004/V3004 to
V3.005/V3005. Run `gen_version.ps1` to regenerate `include/build_version.h`.
Update only the canonical `include/build_version.h` digest in
`tools/release_guard.py` to match the newly generated header.

- [x] **Step 4: Run focused version verification and verify GREEN**

Run:

```powershell
python tools/tests/test_release_identity_contract.py
python tools/tests/test_build_version_refresh.py
python tools/tests/test_dev_release_manifest.py
```

Expected: each script prints `PASS` and exits zero.

### Task 2: OTA/FOTA regression verification

**Files:**
- Test only; no intended source changes.

**Interfaces:**
- Consumes: `FW_VERSION_COUNTER=3005` and existing OTA implementation.
- Produces: host evidence that version checks, package validation, resume, modem handoff, and platform flow remain valid.

- [x] **Step 1: Run focused OTA/FOTA tests**

Run:

```powershell
python tools/tests/test_a300_ota_image.py
python tools/tests/test_fota_package.py
python tools/tests/test_fota_check_parser.py
python tools/tests/test_fota_resume.py
python tools/tests/test_fota_modem_handoff.py
python tools/tests/test_fota_platform_flow.py
```

Expected: all six scripts exit zero and print PASS.

### Task 3: Build immutable V3.005 release

**Files:**
- Create: `artifacts/V3.005/*`
- Generated: `include/build_version.h`

**Interfaces:**
- Consumes: V3.005 release contract and current V3.004 functional source baseline.
- Produces: programming images, OTA package, debug artifacts, and SHA-256 manifest.

- [x] **Step 1: Confirm the target directory does not exist**

Run: `Test-Path -LiteralPath artifacts\V3.005`

Expected: `False`.

- [x] **Step 2: Run the release builder**

Run: `python tools/build_dev_release.py`

Expected: exit zero and creation of `artifacts/V3.005/SHA256SUMS-N32L406CBL7.json`.

- [x] **Step 3: Run release, RAM, stack, and clean-build gates**

Run:

```powershell
make release-guard
make ram-guard
make stack-guard
make all
```

Expected: every command exits zero.

### Task 4: Validate release identity and scope

**Files:**
- Inspect: `artifacts/V3.005/SHA256SUMS-N32L406CBL7.json`
- Inspect: `artifacts/V3.005/A300-406-OTA-V3005.bin`
- Inspect: current Git diff/status.

**Interfaces:**
- Consumes: generated artifacts and manifest.
- Produces: delivery evidence for version, hashes, memory bounds, and unchanged older artifacts.

- [x] **Step 1: Validate all manifest hashes, OTA header fields, image vectors, embedded runtime version, and `git_dirty: true`**

Use a read-only Python validation command. Require OTA magic `0xA300B007`,
version `3005`, product `0x41333030`, body size/CRC agreement, valid App MSP and
reset vector, SHA-256 agreement for every artifact, and the full V3.005 string
inside the App image.

- [x] **Step 2: Confirm V3.003 and V3.004 manifest hashes did not change**

Compare their current manifest and artifact hashes against the recorded JSON
values; report any mismatch as a release blocker.

- [x] **Step 3: Run final source checks**

Run:

```powershell
git diff --check
git status --short
git diff -- release_identity.json README.md include/build_version.h tools/release_guard.py tools/tests/test_release_identity_contract.py
```

Expected: no whitespace errors, no unrelated new edits from this release task,
and no V3.004 references remaining in current-release documentation or identity.
