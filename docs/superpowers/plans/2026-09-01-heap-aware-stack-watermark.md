# Heap-Aware Stack Watermark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent newlib heap writes from being reported as full stack usage and expose the real heap-to-stack RAM gap.

**Architecture:** A host-testable `ram_watermark` module measures heap use, stack peak and untouched gap from explicit memory bounds. `syscalls.c` exposes the allocator's current break without changing allocation behavior, and `main.c` logs the resulting measurements.

**Tech Stack:** C99, ARM GNU Toolchain, N32L406 linker symbols, Python-driven host C tests.

## Global Constraints

- Do not change linker memory sizes, `_sbrk` allocation policy, protocol behavior or retry timing.
- Do not add dynamic allocation or large local buffers.
- Preserve the existing 4096-byte diagnostic safety threshold.
- Do not commit, push, flash or deploy.

---

### Task 1: Host-Tested Watermark Measurement

**Files:**
- Create: `include/ram_watermark.h`
- Create: `src/ram_watermark.c`
- Create: `tools/tests/test_ram_watermark.py`
- Modify: `Makefile`

**Interfaces:**
- Consumes: painted-region start, current heap break, stack top and pattern.
- Produces: `bool ram_watermark_measure(..., ram_watermark_t *out)`.

- [ ] Add a host C harness that paints simulated RAM, writes heap and stack portions, and asserts independent byte counts and invalid-bound rejection.
- [ ] Run `python tools/tests/test_ram_watermark.py`; expect RED because the module is absent.
- [ ] Implement bounded, allocation-free measurement and add the source to `Makefile`.
- [ ] Re-run the test; expect PASS.

### Task 2: Allocator Boundary and Health Integration

**Files:**
- Modify: `include/syscalls.h`
- Modify: `src/syscalls.c`
- Modify: `src/main.c`
- Modify: `tools/tests/test_stack_health_observability.py`

**Interfaces:**
- Consumes: `void *sys_heap_break(void)` and linker symbols `_end`, `_estack`.
- Produces: heap-aware `HEAP_USED`, `STK_PEAK`, `RAM_GAP`, `RAM_AVAIL`, and latched `F` diagnostics.

- [ ] Extend the observability test to require heap-aware fields and reject the old `_ebss`-only scan contract; run it and expect RED.
- [ ] Expose the current break from `_sbrk`, integrate `ram_watermark_measure` in `main.c`, and preserve the 4096-byte fault threshold.
- [ ] Re-run watermark and observability tests; expect PASS.

### Task 3: Regression and Artifact Verification

**Files:**
- Verify: modified sources, tests and `build/a300_firmware.hex`.

**Interfaces:**
- Consumes: Tasks 1-2.
- Produces: fresh firmware for user-controlled HIL testing.

- [ ] Run EC800M, JT808, Flash, identity and RAM diagnostics tests.
- [ ] Run `make all`, `make release-guard`, and `make ram-guard` with the configured STM32CubeIDE make executable.
- [ ] Run scoped `git diff --check`, inspect the diff, and record HEX timestamp and SHA-256.
- [ ] Report that physical HIL must verify a nonzero `RAM_GAP` through registration and authentication.
