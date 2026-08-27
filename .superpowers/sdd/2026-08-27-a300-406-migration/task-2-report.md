# Task 2 report — reliable BY25Q16ES storage service

## Status

Implemented and committed as requested. Existing unrelated working-tree edits
were preserved and not staged.

## Changes

- Added `include/ext_flash_layout.h` as the single 2 MiB BY25Q16ES layout source:
  Candidate (448 KiB), Factory (256 KiB), LKG (256 KiB), Resume/BCR (64 KiB),
  blind-zone (644 KiB), and AGNSS metadata/dual slots. C99 preprocessor
  assertions reject overlaps and out-of-range ends.
- Added `include/ext_flash_store.h` and `src/ext_flash_store.c` with bounded
  owner arbitration, range checks, page-safe verified writes, and 4 KiB
  aligned erase service.
- Hardened `src/spi_flash.c`: all SPI status and WIP polling uses
  `SPI_FLASH_TIMEOUT_MS`; invalid/empty IDs, illegal addresses, transfer
  failures, missing WEL, and timeout conditions return failure. Existing call
  sites remain source-compatible because return values may be ignored.
- Added the storage source to `Makefile`.
- Added `tools/tests/test_ext_flash_layout.py` covering region bounds/non-overlap,
  page-boundary splitting, timeout/error contract markers, and owner API
  presence.

## Verification

```text
python tools/tests/test_ext_flash_layout.py
test_ext_flash_layout: PASS
```

`pytest` is not installed, so the test was run directly as a Python executable.
The Makefile's configured `arm-none-eabi-gcc` path is not present in this
environment; therefore a target syntax compile and full `make` build could not
be run.

`git diff --check` passed for the modified files.

## Concerns

- Hardware validation is still required for the exact BY25Q16ES JEDEC ID and
  SPI electrical timing; the driver fails closed on `0x0000`/`0xFFFF` IDs.
- Existing OTA/configuration/blind-zone modules still call the legacy SPI API;
  migration to explicit owner acquisition should be completed by their future
  tasks while this service remains the common arbitration primitive.

## Review follow-up

- FOTA now uses the Candidate region constants (448 KiB), Resume/BCR pending
  marker, owner lock, verified writes, and propagates storage failures.
- Configuration reads/writes now propagate storage failures and use the config
  owner lock.
- JEDEC ID is validated as `68 40 15`; erase polling uses a separate 500 ms
  deadline (BY25Q16ES worst-case requirement), while read/program keep the
  shorter transaction deadline.
- Host test entry point now executes timeout/owner/JEDEC/FOTA contract checks.

## Second review follow-up

- Defined the configuration region and both redundant slots in
  `ext_flash_layout.h`; `flash_config.h` now aliases those constants instead
  of embedding addresses that conflicted with Candidate/Factory semantics.
- Changed all storage read/write/erase APIs to require the expected owner;
  calls fail unless that owner currently holds the arbiter. Configuration
  initialization and save paths hold CONFIG across complete slot operations.
- Added executable host behavior coverage for owner exclusion, wrong-owner
  rejection, range/alignment checks, and write-error propagation. The test
  skips only when no C compiler is available.
- Added compile-time sector-alignment and exact-boundary assertions for all
  major regions and AGNSS metadata/slots, plus Python checks for AGNSS slot
  sizing and FOTA/config address aliases.

## Second review verification

```text
python tools/tests/test_ext_flash_layout.py
test_ext_flash_layout: PASS
python tools/tests/test_ext_flash_store_host.py
test_ext_flash_store_host: PASS
git diff --check
```
