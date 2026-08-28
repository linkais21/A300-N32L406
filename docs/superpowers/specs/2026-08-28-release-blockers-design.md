# A300_406 Release Blockers Design

## 1. Objective and execution order

Close the four remaining release blockers as four atomic, independently reviewed tasks:

1. Repair the stale external-Flash host fixture and obtain a 25/25 host-test baseline.
2. Replace all legacy `T663B` runtime/build identities with the approved PID/IMEI-derived terminal ID and target firmware version.
3. Implement power-loss-safe blind-zone storage and acknowledged replay on BY25Q16ES external Flash.
4. Execute Task10 ARM build, map/SRAM and hardware release gates, reporting unavailable hardware gates as blocked rather than passed.

No later task starts until the preceding task has passed focused tests, the full applicable regression set, and independent review. Each task receives its own commit. The six pre-existing user-owned dirty files are preserved; if an exact required hunk overlaps one, only that reviewed hunk may be staged.

## 2. Migration boundary and alternatives

This is a feature-level migration into the native N32L406 project. N32G452 SDK, startup, linker, clock, interrupt, peripheral-driver and build-project files must never be copied.

The selected blind-zone approach adapts the proven A300 record/layout behavior into a platform-neutral module backed by `ext_flash_store` and separates persistence from JT808 replay scheduling. A direct source port was rejected because it couples the result to N32G452 headers and raw SPI access. A simplified append-only log was rejected because it provides weaker bounded recovery, wear behavior and torn-write handling.

## 3. Task 1: external-Flash host fixture

Only `tools/tests/test_ext_flash_store_host.py` and its temporary fixture are changed. The fixture must expose `FLASH_TOTAL_SIZE` and `FLASH_SECTOR_SIZE`, provide the required temporary `flash_config.h`, and include the temporary `config.h` before using `config_t`.

The production external-Flash implementation is not changed to accommodate the test. The focused test must first reproduce the current compile failure, then pass with warnings treated according to the existing harness. Completion requires the entire host matrix to report 25 PASS, 0 FAIL and 0 SKIP with `REQUIRE_GCC=1`.

## 4. Task 2: terminal identity and version

One platform-neutral terminal-ID derivation function is the sole source used by JT808 registration and parameter/config refresh paths:

```c
bool terminal_id_derive(const char *pid, const char *imei, char out[8]);
```

Rules are exact:

- A configured PID is valid only when it contains exactly 11 decimal digits; the terminal ID is its last 7 digits.
- When PID is empty, IMEI must be decimal and contain at least 7 digits; the terminal ID is its last 7 digits.
- A non-empty invalid PID does not fall back to IMEI.
- Missing or invalid effective identity returns `false`; JT808 registration is withheld and a bounded diagnostic is emitted.
- `T663B01` and any other model-specific fixed fallback are forbidden.

F39 PID configuration retains its existing 11-digit persisted contract and uses the same derivation function after commit. Tests cover valid PID precedence, empty-PID IMEI fallback, leading zeroes, malformed/short values, output termination, registration rejection, and consistent refresh behavior.

The authoritative version remains `T360-A300_406_20260823000000,V3.000`. Any generated build-version source must be corrected at its source of truth where possible. If the user-owned dirty `include/build_version.h` still contains a legacy identity, the task may stage only the exact version hunk after recording and verifying the surrounding user diff is unchanged.

## 5. Task 3: blind-zone external-Flash store

### 5.1 Persistence layout and API

Blind-zone data remains exclusively in `EXT_FLASH_OWNER_BLIND_ZONE`, starting at `0x110000` with the existing 644 KiB partition. The implementation uses `ext_flash_store`; application code must not call raw `spi_flash_*` APIs.

Use fixed 64-byte location records, one metadata sector and the remaining 640 KiB circular data area. Records contain a magic/version marker, monotonically ordered sequence information, the retained JT808 location payload fields, and CRC. Metadata uses a generation and CRC journal so the newest complete entry can be selected after reset. If metadata is absent or torn, bounded scanning reconstructs head/tail from valid records. A full ring overwrites the oldest record and records that policy diagnostically.

The storage API provides initialize/recover, append, peek-batch and consume-acknowledged operations. `peek` never consumes. Consumption advances and persists metadata only after the matching platform acknowledgment has been accepted. Every Flash operation has bounded owner acquisition and returns busy/error without blocking OTA; OTA retains priority.

### 5.2 Write and replay flow

When a location report cannot be handed to an authenticated online JT808 session, append its compact location record to external Flash. Storage failure must not deadlock the reporting loop and must increment a bounded diagnostic counter.

After reconnect and registration, a bounded replay scheduler peeks records in FIFO order and builds JT808 `0x0704` batch-location messages. Only one replay batch is in flight. The scheduler records the outgoing message serial and consumes exactly that batch only after a successful `0x8001` acknowledgment matching both serial and message ID `0x0704`. Timeout, disconnect, send failure, negative/general failure response, or reboot leaves the records unconsumed for retry. This provides at-least-once delivery; duplicate reports are possible after an acknowledgment/persistence power cut and are preferable to data loss.

Live reporting, watchdog service, modem work and OTA are never held in an unbounded loop. Replay uses a fixed records-per-batch limit derived from existing JT808 buffer capacity and yields between batches.

### 5.3 Verification

Host fault-injection tests cover offline append, reboot recovery, FIFO order, wraparound, full-ring overwrite, record CRC corruption, torn metadata, owner busy/OTA priority, send failure without consume, mismatched/negative acknowledgment without consume, matching acknowledgment consume, reconnect replay, and power loss at each metadata transition. Target hardware must additionally verify BY25Q16ES erase/program timing and replay under modem/OTA contention.

## 6. Task 4: Task10 release gates

Automated gates require a target N32L406 application and bootloader build with no errors and no warnings under the approved warning policy. The real linker map is checked by `tools/map_ram_guard.py`: SRAM is 24 KiB, static RAM plus reserved stack margin must not exceed 20 KiB, application Flash must not exceed 110 KiB, and bootloader Flash must not exceed 11 KiB.

Hardware release evidence must cover EC800M fragmented SMS/CMGS concurrency, UART4 TXDE/TXC fault injection, OTA download/resume/install/power-cut/Trial/LKG/Factory rollback, watchdog and brownout recovery, blind-zone BY25Q16ES replay, and a 72-hour mixed-load soak. A gate is PASS only with a command/log/artifact and observed result. Missing ARM tools, board, programmable power supply, modem/network or server access is reported as an explicit external blocker with a runnable procedure; it is never converted to a PASS.

## 7. Stability invariants

- Static allocation and bounded copies only.
- No unbounded polling, retry, Flash lock, UART wait or modem transaction.
- Watchdog service remains reachable during recovery and replay.
- OTA candidate/resume/BCR partitions and OTA priority remain unchanged.
- Blind-zone corruption cannot affect OTA partitions or prevent boot.
- Registration never transmits an invented identity.
- All changes remain native to N32L406CBL7 and BY25Q16ES.

## 8. Acceptance and review

Each task follows RED/GREEN verification, commits only its scoped files, and receives an independent specification and code-quality review. Critical or Important findings are fixed and re-reviewed before advancing. After all four tasks, a final cross-task review checks release guards, version/identity consistency, external-Flash ownership, OTA non-regression, map budgets and the evidence table for every hardware gate.
