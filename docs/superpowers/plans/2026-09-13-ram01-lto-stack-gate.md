# RAM-01 LTO stack evidence and gate

Goal: replace the non-LTO single-frame safety claim with final-link evidence.
Scope: build tools only; retain RES-01 edits, frozen SRAM/Flash layout and firmware behavior.

Design: collect final LTO and the two non-LTO signature translation-unit
reports at the actual link. Bind their hashes to ELF/MAP in a manifest.
Disassemble that ELF to calculate known direct-call frame sums, including ECC.
List missing library frames, indirect calls, tail transfers and recursion as
coverage gaps; never silently substitute zero for an unknown complete budget.
Keep the 4096-byte runtime gap requirement. A known-frame sum is diagnostic,
not a proven stack maximum. Heap and IRQ/FPU/HIL evidence remain required.
Do not replace 2440 with another unverified constant or disable release LTO.

- [x] Add executable regressions for LTO call accumulation, absent/stale evidence,
  duplicate names, dynamic stack, indirect calls, recursion and budget rejection.
- [x] Implement strict evidence recording/checking in tools/stack_usage_guard.py.
- [x] Connect Makefile, tools/map_ram_guard.py and tools/build_dev_release.py;
  update former non-LTO guard test and retain Flash boundary regressions.
- [x] Run targeted tests, full App build in a new build/ram01-* directory,
  release/stack/RAM gates, compare BIN with audit baseline, inspect diff.
- [x] Document actual numbers, blocked release status and HIL acceptance matrix.

Validation commands: python tools/tests/test_fota_stack_guard.py;
python tools/tests/test_ram_guard.py; python tools/tests/test_lto_stack_guard.py;
make -B all BUILD=build/ram01-20260913; make release-gate
BUILD=build/ram01-20260913; git diff --check.
Expected: host tests and build pass; unproven runtime budget rejects the release
gate, with known call sums and explicit coverage gaps. No release package,
version change, commit, push or device operation is part of this task.
