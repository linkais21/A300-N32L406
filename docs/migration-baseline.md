# A300_406 migration baseline

Captured 2026-08-27 from the existing `A300-first` working tree.

## Working-tree changes at capture

The following files already had uncommitted changes and are intentionally
preserved (not staged by Task 1):

`include/build_version.h`, `include/i2c_accel.h`, `include/tcp_manager.h`,
`src/flash_config.c`, `src/hw_init.c`, `src/i2c_accel.c`, `src/jt808.c`, and
`src/tcp_manager.c`.

## Baseline build

Build command: `make all`

The baseline metadata helper is `tools/tests/baseline_manifest.py`; it records
the current git revision and the byte sizes of `build/a300_firmware.elf` and
`build/a300_firmware.map` when present. It does not modify source files.

Release guard command: `make release-guard`

The guard scans release-controlled source, linker, bootloader, manifest, and
packaging paths for legacy `T663B`, `A300_202511`, and `V1.274` identifiers.
Historical migration documents are intentionally outside its scan paths.
