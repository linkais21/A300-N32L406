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
