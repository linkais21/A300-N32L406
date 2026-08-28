# A300_406 Release Blockers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the host-test, terminal-identity, blind-zone persistence/replay and Task10 evidence blockers without weakening OTA or importing N32G452 platform code.

**Architecture:** Execute four atomic phases in order. Identity is centralized in a platform-neutral derivation service; blind-zone persistence is a CRC-protected external-Flash FIFO separated from a bounded JT808 `0x0704` replay state machine; Task10 consumes real build/map/hardware artifacts rather than inferring release status from host tests.

**Tech Stack:** C99 firmware for N32L406CBL7, BY25Q16ES via `ext_flash_store`, JT808-2013, Python host harnesses, ARM GNU Make builds.

## Global Constraints

- This is feature-level migration; never copy N32G452 SDK, startup, linker, clock, interrupt, peripheral-driver or build-project files.
- Target MCU is N32L406CBL7 at 64 MHz with 128 KiB Flash and 24 KiB SRAM; target external Flash is BY25Q16ES.
- Version is exactly `T360-A300_406_20260823000000,V3.000`.
- OTA candidate/resume/BCR partitions and OTA priority remain unchanged; blind-zone data stays exclusively in `EXT_FLASH_OWNER_BLIND_ZONE` at `0x110000` for 644 KiB.
- Static allocation and bounded waits/copies only; registration never sends an invented terminal identity.
- Preserve the six pre-existing user-owned dirty files. If an exact task hunk overlaps one, record its pre-task diff and stage only the reviewed hunk.
- Run RED/GREEN tests, one scoped commit and independent spec/quality review before starting the next task.

---

### Task 1: Repair the external-Flash host fixture

**Files:**
- Modify: `tools/tests/test_ext_flash_store_host.py`

**Interfaces:**
- Consumes: real `src/ext_flash_store.c` and `src/fota.c`.
- Produces: a temporary host fixture containing `spi_flash.h`, `ext_flash_layout.h`, `ext_flash_store.h`, `config.h`, `flash_config.h`, `fota.h` and a compilable real-code harness.

- [ ] **Step 1: Capture the RED failure**

Run:

```powershell
$env:REQUIRE_GCC='1'; python tools/tests/test_ext_flash_store_host.py
```

Expected: FAIL during the FOTA-lock harness compile because `FLASH_TOTAL_SIZE`, `FLASH_SECTOR_SIZE`, `flash_config.h`, or `config_t` is unavailable. Save the exact compiler output in the task report.

- [ ] **Step 2: Repair only the temporary fixture**

Make the first fixture mirror the already-working owner/bounds fixture: define a 2 MiB `FLASH_TOTAL_SIZE` and 4096-byte `FLASH_SECTOR_SIZE` in temporary `spi_flash.h`, include it from temporary `ext_flash_layout.h`, add the minimum declarations required by real `fota.c` to temporary `flash_config.h`, and include temporary `config.h` in the harness before declaring `config_t`. Do not change production sources or weaken assertions.

- [ ] **Step 3: Verify focused GREEN**

Run the Step 1 command again. Expected: `test_ext_flash_store_host: PASS`, exit 0, with the FOTA acquisition failure leaving the CONFIG owner lock held.

- [ ] **Step 4: Run the complete host matrix**

Run every `tools/tests/test_*.py` individually with `REQUIRE_GCC=1`. Expected total: 25 PASS, 0 FAIL, 0 SKIP. Run `git diff --check` and prove the six protected dirty-file diffs are unchanged.

- [ ] **Step 5: Commit atomically**

Stage only `tools/tests/test_ext_flash_store_host.py` and commit:

```text
test: repair external flash host fixture
```

Request independent spec and code-quality review before Task 2.

### Task 2: Centralize PID/IMEI terminal identity and target version

**Files:**
- Create: `include/terminal_identity.h`
- Create: `src/terminal_identity.c`
- Create: `tools/tests/test_terminal_identity.py`
- Modify: `Makefile`
- Modify: `src/main.c`
- Modify: `src/jt808_params.c`
- Modify: `gen_version.ps1`
- Exact-hunk modify if required: `include/build_version.h`
- Modify: `tools/release_guard.py`

**Interfaces:**
- Produces: `bool terminal_id_derive(const char *pid, const char *imei, char out[8]);`
- Produces: `bool terminal_identity_load(char out[8]);`, which reads `cfg_get()->pid` and `ec800m_get_imei()` then delegates to `terminal_id_derive`.
- Consumes: `device_config_t.pid[12]`, EC800M IMEI, JT808 registration and 0x0107 terminal-info paths.

- [ ] **Step 1: Write the RED identity harness**

Create a real C harness launched by `tools/tests/test_terminal_identity.py`. Assert these literal results: PID `12345678901` plus any IMEI yields `5678901`; empty PID plus IMEI `123456789012345` yields `9012345`; PID `00001234567` yields `1234567`. Assert `false` and an empty output for non-empty malformed PID, 10/12-digit PID, empty/short/non-decimal IMEI, and null arguments. Assert byte 7 is NUL.

Run:

```powershell
$env:REQUIRE_GCC='1'; python tools/tests/test_terminal_identity.py
```

Expected: FAIL because `terminal_identity.h`/implementation does not exist.

- [ ] **Step 2: Implement minimal derivation and integration**

Implement exact validation without allocation. Add the source to `C_SRCS`. Initialize `s_terminal.terminal_id` empty in `main.c`; because EC800M obtains IMEI asynchronously, make `jt808_process` call `terminal_identity_load` before either registration or stored-auth authentication, copy only the derived 7 digits into its private terminal state, and remain offline with a rate-limited `[808] identity invalid` diagnostic until it succeeds. Make the 0x0107 response call the same service and return a JT808 failure response when identity is invalid; it must never use a fixed fallback.

Update any F39 re-registration refresh path so a committed PID re-derives the same identity before reconnect. Tests must prove configured PID wins over IMEI and a non-empty invalid PID never falls through.

- [ ] **Step 3: Correct version generation and release guard**

Change `gen_version.ps1` so `FW_FULL_VERSION` resolves exactly to `T360-A300_406_20260823000000,V3.000` and `FW_BUILD_DATE` remains separately generated. Record `git diff -- include/build_version.h` before editing; if the generated header is required for the build, change/stage only its `FW_FULL_VERSION` line and verify all other pre-existing hunks byte-for-byte unchanged. Extend the release guard behaviorally so it rejects model-specific fixed identity fallbacks and accepts the target version.

- [ ] **Step 4: Verify RED/GREEN and integration behavior**

Run the focused identity harness, F39 config/action/end-to-end tests, feature guard and release guard. Temporarily mutate each consumer to a fixed ID and prove the guard or harness fails, then restore it. Run the 25-test host matrix and `git diff --check`.

- [ ] **Step 5: Commit atomically**

Use path-specific staging; inspect `git diff --cached` to ensure protected unrelated hunks are absent. Commit:

```text
fix: derive JT808 identity from PID or IMEI
```

Request independent spec and code-quality review before Task 3.

### Task 3: Add external-Flash blind-zone FIFO and acknowledged JT808 replay

**Files:**
- Create: `include/blind_zone.h`
- Create: `src/blind_zone.c`
- Create: `include/blind_zone_replay.h`
- Create: `src/blind_zone_replay.c`
- Create: `tools/tests/test_blind_zone_store.py`
- Create: `tools/tests/test_blind_zone_replay.py`
- Modify: `Makefile`
- Modify: `include/jt808.h`
- Modify: `src/jt808.c`
- Modify: `src/main.c`
- Modify: `tools/tests/test_ext_flash_layout.py`

**Interfaces:**
- Produces: `bool blind_zone_init(void);`
- Produces: `void blind_zone_recovery_process(void);` and `bool blind_zone_ready(void);`
- Produces: `blind_zone_result_t blind_zone_append(const blind_zone_record_t *record);`
- Produces: `uint8_t blind_zone_peek(blind_zone_record_t *records, uint8_t capacity, uint32_t *first_sequence);`
- Produces: `blind_zone_result_t blind_zone_consume(uint32_t first_sequence, uint8_t count);`
- Produces: `void blind_zone_replay_process(void);`
- Produces: `void blind_zone_replay_on_general_ack(uint16_t reply_serial, uint16_t reply_msg_id, uint8_t result);`
- Consumes: `EXT_FLASH_OWNER_BLIND_ZONE`, existing compact JT808 location fields, `jt808_send_raw_tracked(..., uint16_t *serial_out)`, TCP/registration state, `0x8001` body `{reply_serial, reply_msg_id, result}`.

- [ ] **Step 1: Write the RED persistence harness**

Use an in-memory 2 MiB NOR fake that enforces one-way programming and 4 KiB sector erase. Tests use hand-built records and assert offline append/reboot FIFO order, a 10,000-record logical capacity within the 10,240 physical slots, one-record oldest overwrite at logical capacity, CRC-corrupt record rejection, newest-valid metadata generation selection, torn metadata recovery scan, and `EXT_FLASH_OWNER_OTA`/other-owner busy returning immediately without changing indices.

Run `python tools/tests/test_blind_zone_store.py`; expect FAIL because the API is absent.

- [ ] **Step 2: Implement the bounded FIFO**

Reserve the first 4 KiB of `EXT_FLASH_BLIND_SIZE` for a metadata journal and use the following 640 KiB as 64-byte records. Define packed on-Flash formats with explicit magic, format version, sequence/generation, indices/count, CRC32 and commit marker. Use `ext_flash_store` only. Expose 10,000 logical records and retain 240 spare physical slots so wraparound can advance one logical record at a time; erase a 4 KiB data sector only after all 64 records in that sector are logically obsolete. Metadata selection is wrap-safe; commit data before metadata. `blind_zone_init` begins recovery, `blind_zone_recovery_process` scans a fixed number of slots per main-loop call, and append/peek return BUSY until `blind_zone_ready` is true. Recovery first reads valid journal entries and, only if none exists, scans at most all 10,240 slots without starving watchdog service. `peek` never consumes; `consume` validates `first_sequence` and count before committing a new metadata generation.

- [ ] **Step 3: Write the RED replay harness**

Assert that offline location-send failure appends once; authenticated reconnect emits FIFO `0x0704` batches within the existing frame body bound; only one batch is in flight; send failure, timeout, disconnect, reboot, mismatched serial, wrong message ID, or nonzero result leaves records intact; exact `0x8001` success consumes exactly the acknowledged batch; subsequent process calls drain later batches. Mutate ACK matching and prove the test fails.

Run `python tools/tests/test_blind_zone_replay.py`; expect FAIL because replay integration is absent.

- [ ] **Step 4: Implement replay and live-report integration**

Factor the existing location-body encoder so both `0x0200` and `0x0704` reuse the same bytes. If an eligible periodic/event location cannot be handed to an authenticated online session, append it; do not recursively store replay failures. Add an explicit JT808 online accessor and a tracked-send API that returns the exact allocated serial for that send, avoiding a race with heartbeat/SMS traffic. Parse the five-byte `0x8001` body and notify replay only when length is valid. Bound records per batch from the real body buffer; do not allocate dynamically or wait for Flash/modem ownership.

- [ ] **Step 5: Verify corruption, contention and regressions**

Run both blind-zone tests, ext-Flash layout/store, FOTA package/resume/BCR/manifest, JT808/F39 end-to-end, RAM model and complete host matrix. Prove external-Flash addresses remain non-overlapping and OTA ownership prevents blind-zone access without releasing OTA's lock. Run `git diff --check` and protected-diff comparison.

- [ ] **Step 6: Commit atomically**

Stage only Task 3 files/hunks and commit:

```text
feat: persist and replay blind-zone locations
```

Request independent spec and code-quality review before Task 4.

### Task 4: Execute Task10 automated and hardware release gates

**Files:**
- Modify after a RED gate proves the current behavior insufficient: `Makefile`, `bootloader/Makefile`, `tools/map_ram_guard.py`
- Create: `docs/task10-release-gates.md`
- Create only when a hardware gate needs machine-verifiable parsing: `tools/task10/parse_task10_log.py`

**Interfaces:**
- Consumes: application ELF/MAP/HEX, bootloader ELF/MAP, serial logs, OTA server artifacts and programmable-power test logs.
- Produces: one evidence table where each gate is `PASS`, `FAIL`, or `BLOCKED`, with command, artifact path and observed result.

- [ ] **Step 1: Locate and fingerprint the target tools**

Check the configured Makefile toolchain directory and PATH for `arm-none-eabi-gcc`, `objcopy`, `size` and a usable Make implementation. Record `--version` output. Missing tools produce a `BLOCKED` entry plus exact installation/path requirement; do not label the build PASS.

- [ ] **Step 2: Build application and bootloader from scoped clean output directories**

Run the native Makefile builds without deleting user source files. Require exit 0, zero compiler/linker warnings, application/bootloader ELF and map artifacts, and target symbols for N32L406 only. Run `tools/release_guard.py`.

- [ ] **Step 3: Enforce real map budgets**

Run `python tools/map_ram_guard.py build/a300_firmware.map`. Extend the guard/test first if necessary so it also checks application Flash ≤110 KiB and bootloader Flash ≤11 KiB while keeping SRAM static ≤20 KiB (24 KiB less 4 KiB stack margin). Record `arm-none-eabi-size` output and map paths.

- [ ] **Step 4: Run hardware matrices**

On the N32L406CBL7/BY25Q16ES board, collect timestamped evidence for fragmented EC800M `+CMT` and CMGS concurrency; UART4 TXDE/TXC stalls/partial frames/receiver reset; OTA fresh/resume/verify/pending/install/Trial/LKG/Factory power cuts; watchdog and brownout recovery; blind-zone reboot/wrap/replay under OTA contention; and a 72-hour mixed JT808/SMS/AGNSS/OTA-capable soak. Each test records firmware hash, board ID, instruments, steps, expected result, observed result and log/artifact checksum.

- [ ] **Step 5: Classify honestly and fix only reproducible software defects**

For a software FAIL, first add a failing host or target regression reproducer, then make the minimal fix, rerun the affected gate and full applicable regression suite. For absent board, modem/network, server or power equipment, leave the gate `BLOCKED` with the executable procedure and required resource. No hardware-only gate may be inferred from static inspection.

- [ ] **Step 6: Commit the evidence atomically**

Commit scripts/fixes plus `docs/task10-release-gates.md` with only evidence actually observed:

```text
test: execute A300_406 release gates
```

Request independent review of commands, artifacts, budget arithmetic and PASS/FAIL/BLOCKED classifications, then request a final whole-plan review.
