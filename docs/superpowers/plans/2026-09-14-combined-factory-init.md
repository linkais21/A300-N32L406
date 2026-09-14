# Combined Factory Initialization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every production Combined SWD programming operation request one power-cut-safe, selective external-Flash factory initialization before the Bootloader jumps to the App, then verify core startup over the debug UART.

**Architecture:** A fixed request record at `0x08005800` is included only when the Bootloader is programmed. The Bootloader validates this record, erases and verifies eight external-Flash metadata sectors, and programs a one-way DONE word before entering the existing BCR selection flow. A Windows production wrapper performs full internal erase/write/verify/reset and a separate standard-library Python parser grades the captured startup log.

**Tech Stack:** C99, ARM GNU Toolchain, N32L40x standard peripheral library, GNU ld, Python 3 host tests, PowerShell/.NET `SerialPort`, STM32 Programmer CLI.

## Global Constraints

- Modify only Bootloader startup behavior, production/release scripts, tests, and documentation; do not change App core behavior.
- Clear configuration A/B, BCR A/B, OTA checkpoint A/B, and OTA authorization A/B on each production Combined programming operation.
- Preserve candidate, Factory, LKG, blind-zone, and AGNSS regions byte-for-byte.
- Normal reset, App-only SWD programming, and OTA must not retrigger initialization.
- Do not weaken the existing fail-closed handling for a damaged current-format BCR.
- Initialization must converge after power loss at every erase/commit boundary.
- The production script may use SWD to program Combined, but startup must not need any post-programming GDB/J-Link/SWD repair command.
- Production GNSS pass means NMEA transport is active with GGA/RMC and zero checksum/format failures; a valid satellite fix is an enhanced result only.
- JT808 `ONLINE` is the network pass condition; FOTA HTTP 401 is a warning in this scope.
- Do not commit, push, deploy, or overwrite existing release artifacts unless the user explicitly authorizes it.

---

### Task 1: Factory-Initialization Contract and State Machine

**Files:**
- Create: `bootloader/include/factory_init.h`
- Create: `bootloader/src/factory_init.c`
- Create: `tools/tests/test_bootloader_factory_init.py`

**Interfaces:**
- Consumes: `image_crc32(const void *, uint32_t)`, `boot_ext_erase()`, `boot_ext_read()`, `boot_watchdog_feed()`.
- Produces: `factory_init_request_t`, `factory_init_result_t`, `factory_init_request()`, `factory_init_apply()`, `boot_factory_mark_complete()`.

- [ ] **Step 1: Write the failing production-C host test**

Create a GCC harness in `test_bootloader_factory_init.py` that compiles the real
`bootloader/src/factory_init.c` and supplies bounded fake external Flash plus
these platform hooks:

```c
bool boot_ext_erase(uint32_t address, uint32_t length);
bool boot_ext_read(uint32_t address, void *data, uint32_t length);
bool boot_factory_mark_complete(uint32_t completion);
void boot_watchdog_feed(void);
uint32_t image_crc32(const void *data, uint32_t length);
```

The test must assert the exact target list:

```c
static const uint32_t expected[] = {
    0x000000UL, 0x001000UL,
    0x100000UL, 0x101000UL,
    0x102000UL, 0x103000UL,
    0x104000UL, 0x105000UL,
};
```

Run scenarios for pending success, already DONE, corrupt request header, unknown
completion, each erase failure, each readback failure, and DONE-program failure.
Seed non-target bytes with `0xA5` and assert they are unchanged. For every
failure boundary, rerun from the resulting Flash state and assert convergence.

- [ ] **Step 2: Run the new test and verify RED**

Run:

```powershell
python tools/tests/test_bootloader_factory_init.py
```

Expected: FAIL because `factory_init.h` and `factory_init.c` do not exist.

- [ ] **Step 3: Define the fixed request contract**

Create `factory_init.h` with the exact packed record and constants:

```c
#define FACTORY_INIT_PAGE_ADDR       0x08005800UL
#define FACTORY_INIT_PAGE_SIZE       0x00000800UL
#define FACTORY_INIT_MAGIC           0x494E4946UL
#define FACTORY_INIT_FORMAT          1U
#define FACTORY_INIT_GENERATION      1UL
#define FACTORY_INIT_SCOPE_ALL       0x0000000FUL
#define FACTORY_INIT_REQUEST_CRC32   0xAF19BCAAUL
#define FACTORY_INIT_COMMIT_MARKER   0x52455144UL
#define FACTORY_INIT_PENDING         0xFFFFFFFFUL
#define FACTORY_INIT_DONE            0x444F4E45UL

typedef struct __attribute__((packed)) {
    uint32_t magic;
    uint16_t format_version;
    uint16_t record_length;
    uint32_t generation;
    uint32_t scope;
    uint32_t crc32;
    uint32_t commit_marker;
    uint32_t completion;
} factory_init_request_t;

typedef enum {
    FACTORY_INIT_RESULT_ERROR = -1,
    FACTORY_INIT_RESULT_ALREADY_DONE = 0,
    FACTORY_INIT_RESULT_APPLIED = 1,
} factory_init_result_t;

const factory_init_request_t *factory_init_request(void);
factory_init_result_t factory_init_apply(const factory_init_request_t *request);
bool boot_factory_mark_complete(uint32_t completion);
```

Add static assertions for the 28-byte record, 4-byte completion alignment, and
the fixed page ending before `APP_FLASH_BASE`.

- [ ] **Step 4: Implement the minimal state machine**

In `factory_init.c`, place the immutable request in the dedicated section:

```c
__attribute__((section(".factory_init_request"), used))
static const factory_init_request_t k_factory_init_request = {
    FACTORY_INIT_MAGIC, FACTORY_INIT_FORMAT,
    sizeof(factory_init_request_t), FACTORY_INIT_GENERATION,
    FACTORY_INIT_SCOPE_ALL, FACTORY_INIT_REQUEST_CRC32,
    FACTORY_INIT_COMMIT_MARKER, FACTORY_INIT_PENDING,
};
```

Validate every header field and recompute CRC through
`image_crc32(request, offsetof(factory_init_request_t, crc32))`. For pending
requests, erase one 4 KiB sector at a time, read it back in a fixed 64-byte
buffer, reject any byte other than `0xFF`, and feed the watchdog between chunks.
Call `boot_factory_mark_complete(FACTORY_INIT_DONE)` only after all eight sectors
verify erased. DONE returns `ALREADY_DONE` without external writes; any other
completion returns `ERROR`.

- [ ] **Step 5: Run the focused test and verify GREEN**

Run:

```powershell
python tools/tests/test_bootloader_factory_init.py
```

Expected: PASS with all success, idempotence, corruption, failure, and power-cut
scenarios reported.

- [ ] **Step 6: Review the task diff without committing**

Run:

```powershell
git diff --check -- bootloader/include/factory_init.h bootloader/src/factory_init.c tools/tests/test_bootloader_factory_init.py
git diff -- bootloader/include/factory_init.h bootloader/src/factory_init.c tools/tests/test_bootloader_factory_init.py
```

Expected: no whitespace errors; no file outside Task 1 changed.

---

### Task 2: Bootloader Platform, Linker, and Startup Integration

**Files:**
- Modify: `bootloader/Makefile`
- Modify: `bootloader/ldscript/n32l406_boot.ld`
- Modify: `bootloader/include/platform_n32l406.h`
- Modify: `bootloader/src/platform_n32l406.c`
- Modify: `bootloader/src/main.c`
- Modify: `tools/tests/test_bootloader_platform_contract.py`
- Modify: `tools/tests/test_bootloader_bcr_failclosed.py`

**Interfaces:**
- Consumes: Task 1 `factory_init_apply(factory_init_request())`.
- Produces: fixed marker placement, N32 internal completion programming, and the startup ordering guarantee that factory initialization precedes all BCR reads.

- [ ] **Step 1: Extend existing tests for the new startup ordering and platform boundary**

Add mocks for `factory_init_request()` and `factory_init_apply()` to every host
harness compiling `bootloader/src/main.c`. Add assertions that:

```c
boot_platform_init();
factory_init_apply(factory_init_request());
bcr_note_trial_reset(...);
bootloader_select_image();
```

occur in that order, and that a factory-init error reaches the existing bounded
recovery loop without calling BCR or jump code. Add source-contract assertions
that completion programming accepts only the fixed completion address/value,
uses `FLASH_ProgramWord`, verifies readback, and always relocks internal Flash.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```powershell
python tools/tests/test_bootloader_platform_contract.py
python tools/tests/test_bootloader_bcr_failclosed.py
```

Expected: FAIL because the new source, platform hook, and startup call are not integrated.

- [ ] **Step 3: Reserve the final Bootloader page and include the source**

Change the linker memory regions to code `0x08000000-0x080057FF` and factory
request `0x08005800-0x08005FFF`. Add:

```ld
.factory_init_request 0x08005800 : {
  KEEP(*(.factory_init_request))
} > FACTORY_INIT
ASSERT(SIZEOF(.factory_init_request) == 28,
       "factory init request wire size mismatch")
ASSERT(_boot_code_end <= 0x08005800,
       "bootloader code overlaps factory init page")
```

Add `src/factory_init.c` to `SRCS` in `bootloader/Makefile`.

- [ ] **Step 4: Implement the fixed-address completion hook**

Expose the hook in `platform_n32l406.h`. In `platform_n32l406.c`, reject any
value other than `FACTORY_INIT_DONE`, calculate the address with
`FACTORY_INIT_PAGE_ADDR + offsetof(factory_init_request_t, completion)`, require
the current word to be `FACTORY_INIT_PENDING`, program one word, read it back,
and call `FLASH_Lock()` on every post-unlock path.

- [ ] **Step 5: Gate BCR processing on factory initialization**

In `bootloader/src/main.c`, immediately after successful `boot_platform_init()`:

```c
if (factory_init_apply(factory_init_request()) == FACTORY_INIT_RESULT_ERROR) {
    for (;;) { boot_recovery_step(); boot_watchdog_feed(); }
}
```

Leave all existing BCR selection and fail-closed branches unchanged.

- [ ] **Step 6: Run focused tests and Bootloader build**

Run:

```powershell
python tools/tests/test_bootloader_factory_init.py
python tools/tests/test_bootloader_platform_contract.py
python tools/tests/test_bootloader_bcr_failclosed.py
make -C bootloader -B all
python tools/map_ram_guard.py bootloader bootloader/build/bootloader.map
```

Expected: all host tests PASS; Bootloader builds; marker section is exactly at
`0x08005800`; code does not overlap it; RAM guard passes.

- [ ] **Step 7: Review the task diff without committing**

Run `git diff --check` and inspect only the Task 2 files plus Task 1 files.

---

### Task 3: Combined Artifact Contract

**Files:**
- Modify: `tools/build_dev_release.py`
- Create: `tools/tests/test_factory_init_artifact.py`
- Modify: `tools/tests/test_dev_release_manifest.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 2 fixed marker section and existing release builder outputs.
- Produces: release-time proof that every Combined image carries a pending request and retains App offset `0x6000`.

- [ ] **Step 1: Write failing artifact tests**

Add a test that reads the Bootloader ELF with `arm-none-eabi-objdump -h`, reads
the Bootloader BIN and a temporary Combined byte array, and asserts:

```python
FACTORY_OFFSET = 0x5800
APP_OFFSET = 0x6000
RECORD = struct.Struct("<IHHIIIII")
assert marker.magic == 0x494E4946
assert marker.format_version == 1
assert marker.record_length == RECORD.size
assert marker.generation == 1
assert marker.scope == 0x0F
assert marker.crc32 == 0xAF19BCAA
assert marker.commit_marker == 0x52455144
assert marker.completion == 0xFFFFFFFF
```

Also assert the Combined App vectors at `0x6000` satisfy the existing MSP and
Thumb reset-vector bounds.

- [ ] **Step 2: Run artifact tests and verify RED**

Run:

```powershell
python tools/tests/test_factory_init_artifact.py
python tools/tests/test_dev_release_manifest.py
```

Expected: FAIL because the release builder does not validate the marker contract.

- [ ] **Step 3: Add release-builder validation**

Before reserving or writing a release directory, have `build_dev_release.py`
validate the Bootloader marker fields from the freshly built BIN, reject a
missing/truncated/DONE marker, and validate the App vectors after constructing
Combined. Keep immutable artifact behavior unchanged and do not overwrite any
existing version directory.

- [ ] **Step 4: Document the programming semantics**

Update `README.md` to distinguish:

- App-only SWD/OTA: preserves DONE and external configuration;
- production Combined: erases/reprograms the internal marker page and triggers
  one selective initialization;
- MCU internal mass erase does not itself erase BY25Q16;
- Factory/LKG/candidate/blind-zone/AGNSS remain preserved by Bootloader policy.

- [ ] **Step 5: Run artifact/release tests and verify GREEN**

Run:

```powershell
python tools/tests/test_factory_init_artifact.py
python tools/tests/test_dev_release_manifest.py
python tools/tests/test_release_identity_contract.py
```

Expected: PASS without creating or overwriting a release directory.

- [ ] **Step 6: Review the task diff without committing**

Run `git diff --check` and verify existing user changes in
`tools/build_dev_release.py` and `README.md` remain intact.

---

### Task 4: Post-Flash Self-Test Parser

**Files:**
- Create: `tools/production_selftest.py`
- Create: `tools/tests/test_production_selftest.py`

**Interfaces:**
- Consumes: UTF-8/ASCII debug-UART capture file.
- Produces: exit `0` for core pass, nonzero for a missing mandatory stage; sanitized console summary; FOTA 401 warning; GNSS `NO_FIX` enhanced status.

- [ ] **Step 1: Write failing parser tests**

Use synthetic logs only. Cover success, each missing mandatory stage, `RX=0`,
missing GGA/RMC, nonzero CS/FMT, GPS no-fix, FOTA 401, malformed counters, and
redaction of 15-digit IMEI, 19/20-digit ICCID, latitude/longitude, IPv4 address,
and API-key-like values. Assert raw sensitive values never appear in stdout or
stderr.

- [ ] **Step 2: Run parser tests and verify RED**

Run:

```powershell
python tools/tests/test_production_selftest.py
```

Expected: FAIL because `production_selftest.py` does not exist.

- [ ] **Step 3: Implement the bounded parser**

Implement a single-pass line parser with mandatory stage flags for:

```python
MANDATORY = ("boot", "flash", "modem", "jt808", "gnss")
```

Accept `[BOOT] ready`, `JEDEC=684015`, `[4G] ready`, `[808] ch0 ONLINE`, and a
`[GPS]` counter line with `RX/GGA/RMC > 0` and `CS/FMT == 0`. Treat `GPS=1` as
`FIX`, otherwise `NO_FIX`. Treat `HTTP response status=401` as warning only.
Redact before printing or writing any derived diagnostic.

- [ ] **Step 4: Run parser tests and verify GREEN**

Run:

```powershell
python tools/tests/test_production_selftest.py
```

Expected: PASS for grading, warning, timeout-stage, and redaction cases.

- [ ] **Step 5: Review the task diff without committing**

Run `git diff --check` for the two Task 4 files.

---

### Task 5: Production Combined Flash Wrapper and Full Verification

**Files:**
- Create: `tools/flash_combined_and_selftest.ps1`
- Create: `tools/tests/test_flash_combined_script.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: an existing `Combined-N32L406CBL7.bin`, SWD probe, configurable COM port, existing `PROG_CLI` path or explicit `-ProgrammerPath`.
- Produces: internal erase/write/verify/reset followed by bounded UART capture and Task 4 grading; no post-programming SWD repair.

- [ ] **Step 1: Write failing wrapper contract tests**

Test the script text and a `-DryRun` mode. Assert it validates the Combined
marker before hardware access, invokes full internal erase, writes the binary at
`0x08000000`, requests verify and reset, opens `115200 8N1` with DTR/RTS false,
uses a finite default timeout of 180 seconds, and invokes
`production_selftest.py`. Assert a missing/invalid marker fails before invoking
the programmer.

- [ ] **Step 2: Run wrapper tests and verify RED**

Run:

```powershell
python tools/tests/test_flash_combined_script.py
```

Expected: FAIL because the wrapper does not exist.

- [ ] **Step 3: Implement the production wrapper**

Add parameters:

```powershell
param(
    [Parameter(Mandatory=$true)][string]$CombinedPath,
    [Parameter(Mandatory=$true)][string]$Port,
    [string]$ProgrammerPath,
    [ValidateRange(30,600)][int]$TimeoutSeconds = 180,
    [switch]$DryRun
)
```

Resolve exact paths, validate the marker bytes at offset `0x5800`, reject files
without valid App vectors at `0x6000`, and execute the existing programmer as
separate checked operations: connect/full internal erase, write Combined at
`0x08000000` with verify, then reset. Capture UART without transmitting bytes,
store the raw capture only in a uniquely named temporary file, pass it to
`production_selftest.py`, and delete it in `finally`. Never print raw log lines.

- [ ] **Step 4: Run wrapper tests and dry-run validation**

Run:

```powershell
python tools/tests/test_flash_combined_script.py
powershell -NoProfile -ExecutionPolicy Bypass -File tools/flash_combined_and_selftest.ps1 -CombinedPath artifacts/HIL-STABILITY-20260913-V3040-V3041/V3.040/Combined-N32L406CBL7.bin -Port COM4 -DryRun
```

Expected: tests PASS; dry-run prints validated erase/write/verify/reset and
self-test stages without opening SWD or COM4.

- [ ] **Step 5: Run firmware and host regression gates**

Run from `A300-first/`:

```powershell
python tools/tests/test_bootloader_factory_init.py
python tools/tests/test_bootloader_platform_contract.py
python tools/tests/test_bootloader_bcr_failclosed.py
python tools/tests/test_ext_flash_layout.py
python tools/tests/test_factory_init_artifact.py
python tools/tests/test_dev_release_manifest.py
python tools/tests/test_production_selftest.py
python tools/tests/test_flash_combined_script.py
python tools/tests/test_feature_guards.py
python tools/tests/test_blind_zone_store.py
python tools/tests/test_blind_zone_replay.py
python tools/tests/test_ext_flash_store_host.py
make -C bootloader -B all
make -B all
make release-guard
make ram-guard
git diff --check
```

Expected: all applicable host tests and builds pass. If an existing RAM/release
gate remains blocked by the documented baseline, report its first actual failure
without claiming a full release pass.

- [ ] **Step 6: Perform scoped diff and secret review**

Inspect `git diff --stat`, `git diff --` for every touched file, and verify no
real IMEI, ICCID, device key, location, server credential, temporary capture, or
generated firmware artifact is tracked.

- [ ] **Step 7: Record required hardware/HIL validation without executing it automatically**

Report these outstanding tests unless the user separately authorizes hardware
programming: production Combined flash, first boot, second reset without erase,
power cut after each of eight external erases, power cut before DONE, EC800M/eSIM
registration, JT808 ONLINE, GNSS NMEA transport, and outdoor valid fix.
