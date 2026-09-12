# Runtime Stability Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden watchdog diagnostics, post-reset modem identity recovery, mileage persistence endurance, and DA218E INT1 latch handling without changing shallow sleep or JT808 0x0200 timestamp behavior.

**Architecture:** Keep each recovery policy at its existing ownership boundary. `reset_diag` owns an eight-word RTC backup record, EC800M owns identity validity while TCP consumes that readiness, `flash_config` owns mileage dirty state while `mileage` owns time-based flush scheduling, and the accelerometer/main-loop adapter owns bounded INT1 re-arm attempts.

**Tech Stack:** C99, ARM GNU Toolchain, N32L40x SPL/CMSIS, Python-driven host C harnesses, Make.

## Global Constraints

- Keep `A300_STOP1_SLEEP=0` and the current shallow-WFI behavior unchanged.
- Do not change JT808 0x0200 retained-position or timestamp behavior.
- Preserve all pre-existing uncommitted vibration/work-mode changes in the current worktree.
- Do not write Flash or perform blocking work from an ISR or HardFault handler.
- All retry loops and recovery paths remain bounded.
- Do not commit, push, flash hardware, or overwrite release artifacts.

---

### Task 1: Persistent Reset and HardFault Diagnostics

**Files:**
- Modify: `include/reset_diag.h`
- Modify: `src/reset_diag.c`
- Modify: `src/main.c`
- Test: `tools/tests/test_reset_diag.py`

**Interfaces:**
- Produces: `reset_diag_runtime_init()`, `reset_diag_loop_begin()`, `reset_diag_mark_phase(reset_diag_phase_t)`, `reset_diag_record_fault(pc, lr, cfsr, hfsr)`, `reset_diag_previous(reset_diag_snapshot_t *)`, and `reset_diag_phase_name()`.
- Storage: RTC `BKP13R..BKP20R`; packed phase and fault words include 16-bit complements, and the magic/version word is committed last.

- [ ] **Step 1: Replace the source-text reset test with a host C harness**

  The harness supplies eight fake backup words and fake RCC reset flags. It verifies invalid magic is ignored, a valid phase/sequence survives simulated IWDG reset, a committed HardFault preserves PC/LR/CFSR/HFSR, corrupted complement fields are rejected, and initializing a new boot record clears the live fault marker without losing the captured previous snapshot.

- [ ] **Step 2: Run the reset harness and verify RED**

  Run: `python tools/tests/test_reset_diag.py`

  Expected: compilation fails because the snapshot, phase, runtime-init, and fault-record APIs do not exist.

- [ ] **Step 3: Implement the backup record and boot capture**

  Add target accessors for `RTC->BKP13R` through `RTC->BKP20R` and host-test accessors for a fake word array. Enable PWR backup access during runtime initialization, validate the prior record into RAM, then commit a clean current-boot record. Do not erase RTC calendar state.

- [ ] **Step 4: Capture HardFault context and main-loop phases**

  Replace the printing HardFault with a naked MSP/PSP stack selector that passes stacked LR/PC plus SCB CFSR/HFSR to `reset_diag_record_fault()`, then waits without feeding IWDG so the existing watchdog recovery remains fail-closed. Mark a new loop sequence and named phase immediately before every major main-loop service call.

- [ ] **Step 5: Run the reset harness and verify GREEN**

  Run: `python tools/tests/test_reset_diag.py`

  Expected: `test_reset_diag: PASS`.

### Task 2: EC800M Identity Recovery and TCP Gate

**Files:**
- Modify: `include/ec800m.h`
- Modify: `src/ec800m.c`
- Modify: `src/tcp_manager.c`
- Modify: `tools/tests/test_ec800m_identity_recovery.py`
- Create: `tools/tests/test_tcp_identity_gate.py`

**Interfaces:**
- Produces: `bool ec800m_identity_ready(void)`.
- Consumes: existing IMEI 15-digit validation, ICCID 19/20-character validation, identity retry limit of three attempts, and `EC800M_STATE_INIT` step 6.

- [ ] **Step 1: Add failing READY-recovery and TCP-gate tests**

  Extend the real `ec800m.c` host harness so READY with missing identity returns to INIT step 6 and valid identity stays READY. Add a real `tcp_manager.c` harness that proves `ec800m_is_ready()==true` with invalid identity performs zero TCP opens, then valid identity allows one open.

- [ ] **Step 2: Run both identity tests and verify RED**

  Run: `python tools/tests/test_ec800m_identity_recovery.py`

  Run: `python tools/tests/test_tcp_identity_gate.py`

  Expected: missing public identity API and READY recovery make both tests fail.

- [ ] **Step 3: Implement identity validity and bounded refresh**

  Export `ec800m_identity_ready()`. In READY, invalid identity closes the READY gate, clears identity attempt counters, sets init step 6, and transitions to INIT without resetting the module. Existing three-attempt IMEI/ICCID handling remains the only path that power-cycles the modem after repeated query failure.

- [ ] **Step 4: Gate all TCP connection starts on identity**

  Require both modem READY and identity READY in `CS_WAIT_MODEM` and `CS_BACKOFF`; an online channel returns to `CS_WAIT_MODEM` if either condition becomes false. Do not print the boot identity/server summary until the identity gate passes.

- [ ] **Step 5: Run both identity tests and verify GREEN**

  Expected: both Python host harnesses print PASS and exit zero.

### Task 3: Deferred Mileage Persistence

**Files:**
- Modify: `include/flash_config.h`
- Modify: `src/flash_config.c`
- Modify: `include/mileage.h`
- Modify: `src/mileage.c`
- Modify: `src/main.c`
- Modify: `src/adc_monitor.c`
- Modify: `tools/tests/test_flash_config_v3.py`
- Create: `tools/tests/test_mileage_persistence.py`
- Create: `tools/tests/test_adc_power_loss_mileage.py`

**Interfaces:**
- Produces: `bool cfg_mileage_dirty(void)`, `bool cfg_flush_mileage(void)`, `void mileage_persist_process(uint32_t now_ms)`, and `bool mileage_force_save(uint32_t now_ms)`.
- Timing: first dirty mileage is due after 600000 ms; a failed periodic or forced flush retries no earlier than 30000 ms.

- [ ] **Step 1: Add failing Flash endurance tests**

  Extend the NOR harness to prove hundreds of `cfg_add_mileage()` calls update RAM with zero erase/program operations, one successful flush persists the latest total, a failed flush keeps dirty state, and a successful unrelated live-config save clears mileage dirty state because it persisted the same RAM image.

- [ ] **Step 2: Add failing scheduler and power-loss tests**

  Compile real `mileage.c` with controlled GPS/config/time dependencies and verify no save before 600000 ms, one save at the deadline, 30000 ms failure backoff, immediate force-save, and no distance on the first GNSS point. Compile real `adc_monitor.c` with controlled ADC samples and verify a >9 V to <4 V transition forces one mileage save alongside the existing power-cut alarm.

- [ ] **Step 3: Run mileage tests and verify RED**

  Run the three mileage/Flash test scripts. Expected: missing dirty/flush/scheduler APIs or unexpected Flash operations fail.

- [ ] **Step 4: Implement RAM accumulation and transactional dirty state**

  Change only the mileage setters to mutate RAM and mark dirty. A successful write of the live `s_cfg` image clears dirty; a failed write preserves it. All non-mileage setters retain immediate saves.

- [ ] **Step 5: Implement periodic and forced flush policies**

  Run the periodic scheduler once per main loop after `mileage_update()`. Force a flush immediately after the work-mode step enters stationary sleep and on ADC vehicle-power loss. A failed force does not block state transition and remains dirty for bounded retry.

- [ ] **Step 6: Run mileage tests and verify GREEN**

  Expected: all three host harnesses pass.

### Task 4: DA218E INT1 Initialization and Bounded Re-arm

**Files:**
- Modify: `include/i2c_accel.h`
- Modify: `src/i2c_accel.c`
- Modify: `src/main.c`
- Modify: `src/work_mode_sleep.c`
- Modify: `tools/tests/test_i2c_accel_vibration_adapter.py`
- Modify: `tools/tests/test_vibration_wake_optimization.py`
- Create: `tools/tests/test_i2c_accel_int1_rearm.py`

**Interfaces:**
- Produces: accelerometer diagnostics for final re-arm success/failure and sampled PB3 INT1 level.
- Consumes: existing `i2c_accel_rearm_wake_interrupt()` and six-second two-thirds-hit work-mode confirmation.

- [ ] **Step 1: Add a failing real-driver INT1 harness**

  Compile real `i2c_accel.c` with an emulated DA218E register bus. Verify successful sensor initialization writes the final reset sequence after all motion registers, samples PB3 once, exposes the sampled level, and reports failure without authorizing motion when either reset write fails.

- [ ] **Step 2: Tighten bounded window re-arm regression coverage**

  Verify one consumed vibration window schedules one re-arm episode, at most one transaction is attempted per later main-loop pass, the third failure latches shallow fallback, and no PB3 level alone enters REALTIME.

- [ ] **Step 3: Run INT1 tests and verify RED**

  Run: `python tools/tests/test_i2c_accel_int1_rearm.py`

  Run: `python tools/tests/test_vibration_wake_optimization.py`

  Expected: startup final re-arm diagnostics are missing.

- [ ] **Step 4: Implement startup final re-arm and diagnostics**

  After all active-motion registers are configured, execute one bounded reset/restore sequence, sample PB3, update diagnostics, and emit one initialization diagnostic. Keep sampled-high informational only.

- [ ] **Step 5: Preserve bounded shallow fallback**

  Keep the existing main-loop three-pass retry state. Remove any duplicate STOP admission re-arm that can reset the latch continuously; when the bounded episode fails, allow shallow WFI and software vibration polling to continue.

- [ ] **Step 6: Run INT1 and work-mode tests and verify GREEN**

  Expected: INT1 harness, vibration adapter, vibration policy, work-mode policy, and shallow-sleep contract all pass.

### Task 5: Integrated Verification

**Files:**
- Inspect: all modified files and the current nested-repository diff.

- [ ] **Step 1: Run targeted host regressions**

  Run all reset, identity, mileage, accelerometer, vibration, shallow-sleep, work-mode, and Flash configuration tests touched by the four tasks.

- [ ] **Step 2: Run firmware and release guards**

  Run: `make all`

  Run: `make release-guard`

  Run: `make ram-guard`

- [ ] **Step 3: Audit the final diff**

  Run: `git diff --check`

  Run: `git status --short`

  Confirm `A300_STOP1_SLEEP` and 0x0200 time/location code are unchanged, no sensitive serial-log values entered source/tests/docs, and only scoped files plus pre-existing user changes are present.

- [ ] **Step 4: Record hardware validation gaps**

  Report RTC-backup retention across IWDG, live EC800M post-MCU-reset identity recovery, DA218E PB3 latch behavior, and long-drive Flash generation behavior as requiring real-device/HIL verification.
