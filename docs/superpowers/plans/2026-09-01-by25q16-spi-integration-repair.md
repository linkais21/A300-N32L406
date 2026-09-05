# BY25Q16ES SPI Integration Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the N32L406-to-BY25Q16ES SPI interface and provide bounded, actionable diagnostics for configuration persistence failures.

**Architecture:** Keep existing Flash APIs and ownership/transaction layers. Correct the MCU input pin configuration at the hardware boundary, add a compact diagnostic state to the SPI driver, and surface that state only when initialization or configuration persistence fails.

**Tech Stack:** C99, N32L40x SPL 2.2.0, BY25Q16ES SPI NOR, Python host-C harnesses, GNU Make.

## Global Constraints

- Do not rewrite SR1/SR2/SR3 protection bits automatically.
- Do not change external-Flash layout or persisted configuration format.
- Preserve unrelated user worktree changes.
- Do not flash hardware, commit, push or deploy.
- Hardware behavior remains subject to real-device/HIL verification.

---

### Task 1: MISO hardware contract

**Files:**
- Modify: `tools/tests/test_hardware_pin_contract.py`
- Modify: `src/hw_init.c`

**Interfaces:**
- Consumes: `FLASH_MISO_PIN`, `FLASH_MISO_PORT` from `include/config.h`.
- Produces: PA6 configured as `GPIO_Mode_Input` in `hw_spi_init()`.

- [ ] Add a source-contract assertion that isolates the MISO initialization block and requires `GPIO_Mode_Input` before `GPIO_InitPeripheral(FLASH_MISO_PORT, &g)`.
- [ ] Run `python tools/tests/test_hardware_pin_contract.py`; expect failure because MISO is currently `GPIO_Mode_AF_PP`.
- [ ] Change only the MISO mode assignment to `GPIO_Mode_Input`.
- [ ] Re-run the contract test; expect PASS.

### Task 2: SPI diagnostic state and initialization

**Files:**
- Modify: `include/spi_flash.h`
- Modify: `src/spi_flash.c`
- Modify: `tools/tests/test_ext_flash_store_host.py`

**Interfaces:**
- Produces: `spi_flash_failure_t`, `spi_flash_diagnostics_t`, `spi_flash_get_diagnostics()` and `spi_flash_failure_name()`.
- Preserves: all existing read/write/erase function signatures.

- [ ] Extend the host harness with assertions for full JEDEC ID `0x684015`, SR1/SR2/SR3 capture, WEL failure classification, protected erase classification, WIP timeout, and successful program.
- [ ] Run `python tools/tests/test_ext_flash_store_host.py`; expect compile/assertion failure because the diagnostic API does not exist.
- [ ] Add the minimal public diagnostic types/API and implement bounded status reads (`05H/35H/15H`), CS-high plus 1 ms initialization delay, and last-failure tracking.
- [ ] Classify ID, READY, WREN, PROTECTED, ERASE, PROGRAM and VERIFY without issuing status-register writes.
- [ ] Re-run the host harness; expect PASS.

### Task 3: Configuration persistence diagnostics

**Files:**
- Modify: `src/flash_config.c`
- Modify: `tools/tests/test_flash_config_v3.py`

**Interfaces:**
- Consumes: `spi_flash_get_diagnostics()` and `spi_flash_failure_name()`.
- Produces: bounded `[CFG] defaults persisted ...` and `[CFG] persist failed ...` logs.

- [ ] Capture debug output in the configuration harness and assert success and injected failure logs.
- [ ] Run `python tools/tests/test_flash_config_v3.py`; expect assertion failure because persistence results are not logged.
- [ ] Add minimal logging around default-slot persistence while retaining the redundant transaction and activation rules.
- [ ] Re-run the configuration harness; expect PASS.

### Task 4: Regression and build verification

**Files:**
- Review only the scoped diff plus generated build outputs.

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces: host-test, build, release-guard and RAM-guard evidence.

- [ ] Run focused tests: hardware pin contract, external Flash store, Flash config v3, terminal identity and external Flash layout.
- [ ] Run `make all`, `make release-guard`, and `make ram-guard`.
- [ ] Run `git diff --check` and inspect the scoped diff for secrets, debug leftovers and unrelated edits.
- [ ] Report that real-device/HIL verification is still required and provide the expected boot-log acceptance criteria.
