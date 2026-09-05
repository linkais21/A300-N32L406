# A300-T9 Work Mode STOP1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the confirmed A300-T9 real-time/stationary work-mode state machine with logical ACC reporting, independent heartbeat/location timers, GPS-off online STOP1 sleep, interrupt/RTC wake handling, and bounded fallback behavior.

**Architecture:** Keep policy in a host-testable `work_mode` state machine. Put N32L406 RTC/STOP1, clock restoration, UART/DMA restoration, GPS gating, and modem service-window code behind `work_mode_sleep`; keep JT808 and G-sensor changes as narrow adapters. Retire the existing competing ACTIVE/IDLE/SLEEP/DEEP_SLEEP policy from `power_mgr` while preserving only low-level wake/STOP helpers needed by the new state machine.

**Tech Stack:** C99, N32L40x standard peripheral library, existing A300 firmware modules, Python standard-library host tests, GNU ARM Makefile.

## Global Constraints

- Do not add third-party libraries.
- Modify only work-mode-related files plus the minimum integration hooks in `main.c`, `jt808.c/.h`, `i2c_accel.c/.h`, `flash_config.c`, `at_config.c`, `power_mgr.c/.h`, and `Makefile`.
- Keep ACC polarity PA12 high = ON; do not copy N32G452 inverted polarity.
- Keep blind-zone v3 format, external Flash layout, and online complete `0x0200` extension format unchanged.
- ISR code may only clear flags, sample/latch events, and hand off; no JT808 parsing, Flash writes, dynamic allocation, or unbounded loops in ISR.
- All waits, retries, service windows, and STOP1 segments are bounded; no infinite retry or blocking modem wait.
- `report_moving_s` default is 30 seconds, `report_stopped_s` default is 180 seconds, and `heartbeat_s` default is 180 seconds; all runtime intervals remain configurable through existing SMS/F39/JT808 paths.
- Preserve unrelated dirty-worktree changes and do not commit, push, flash, deploy, or overwrite firmware artifacts unless explicitly requested.
- Hardware behavior remains subject to real-device/HIL verification.

## File Map

- Create `include/work_mode.h` and `src/work_mode.c`: pure policy state, event latches, logical ACC, vibration confirmation, deadlines, and action queue.
- Create `include/work_mode_sleep.h` and `src/work_mode_sleep.c`: RTC 15-second wake slices, STOP1 entry/exit, service-window admission, and shallow-sleep fallback.
- Modify `include/power_mgr.h` and `src/power_mgr.c`: remove the old competing four-state policy and retain only compatibility wrappers or low-level EXTI wake routing required by `work_mode_sleep`.
- Modify `include/i2c_accel.h` and `src/i2c_accel.c`: expose bounded sensitivity-level-10 sample hits while leaving register/I2C ownership local to the driver.
- Modify `include/jt808.h` and `src/jt808.c`: logical ACC override, immediate/historical location report entry point, and alarm-bit report support.
- Modify `src/flash_config.c`, `src/at_config.c`, and the existing configuration callback path: defaults and immediate deadline refresh after runtime configuration changes.
- Modify `src/main.c`: initialize and drive work mode, route alarm events, and preserve the existing modem/GPS/TCP/JT808 order.
- Modify `Makefile`: compile the two new source files.
- Create `tools/tests/test_work_mode_policy.py`, `tools/tests/test_work_mode_contract.py`, and `tools/tests/test_work_mode_jt808_contract.py` for host-level policy and source contracts.

---

### Task 1: Add the Pure Work-Mode Policy Core

**Files:**
- Create: `include/work_mode.h`
- Create: `src/work_mode.c`
- Test: `tools/tests/test_work_mode_policy.py`

**Interfaces:**
- `typedef enum { WORK_MODE_BOOT_MONITOR, WORK_MODE_REALTIME, WORK_MODE_STATIONARY_SLEEP } work_mode_state_t;`
- `typedef struct { uint16_t report_moving_s; uint16_t report_stopped_s; uint16_t heartbeat_s; uint32_t stationary_timeout_s; uint32_t vibration_confirm_s; } work_mode_config_t;`
- `typedef struct { uint32_t now_s; bool acc_high; bool vibration_hit; bool rtc_wake; uint32_t alarm_bits; bool gps_valid; } work_mode_input_t;`
- `typedef enum { WORK_ACTION_NONE, WORK_ACTION_SET_LOGICAL_ACC, WORK_ACTION_GPS_ON, WORK_ACTION_GPS_OFF, WORK_ACTION_REPORT_ENTRY, WORK_ACTION_REPORT_LOCATION, WORK_ACTION_REPORT_HEARTBEAT, WORK_ACTION_REPORT_ALARM, WORK_ACTION_ENTER_STOP1 } work_mode_action_type_t;`
- `typedef struct { work_mode_action_type_t type; bool acc_on; uint32_t alarm_bits; bool historical_position; } work_mode_action_t;`
- `void work_mode_init(const work_mode_config_t *cfg, uint32_t now_s, bool acc_high);`
- `void work_mode_configure(const work_mode_config_t *cfg, uint32_t now_s);`
- `void work_mode_step(const work_mode_input_t *input);`
- `bool work_mode_next_action(work_mode_action_t *out);`
- `work_mode_state_t work_mode_state(void);`
- `bool work_mode_logical_acc(void);`

- [ ] **Step 1: Write failing policy tests** covering PA12-high boot entry, five-minute stationary entry, six-second vibration confirmation, ACC falling-edge priority, one-shot mode-entry actions, independent 180-second heartbeat/location deadlines, simultaneous two-action expiry, alarm-only reporting without state change, time wraparound, and bounded retry flags.
- [ ] **Step 2: Run the policy tests and verify they fail**.

Run: `python tools/tests/test_work_mode_policy.py`

Expected: FAIL because `work_mode.h`/`work_mode.c` do not exist.

- [ ] **Step 3: Implement the minimal deterministic state machine** with unsigned wrap-safe elapsed comparisons, a six-second consecutive-hit counter, a five-minute boot stationary timer, ACC edge tracking, alarm latching, independent heartbeat/location deadlines, and a fixed-size action queue. ACC falling edge must enqueue ACC OFF entry before processing vibration or ACC-high actions.
- [ ] **Step 4: Run policy tests and verify they pass**.

Run: `python tools/tests/test_work_mode_policy.py`

Expected: PASS.

- [ ] **Step 5: Run formatting/scope checks**.

Run: `git diff --check -- include/work_mode.h src/work_mode.c tools/tests/test_work_mode_policy.py`

Expected: no output and exit code 0.

### Task 2: Add G-Sensor Sensitivity-Level Adapter

**Files:**
- Modify: `include/i2c_accel.h`
- Modify: `src/i2c_accel.c`
- Modify: `tools/tests/test_work_mode_policy.py`

**Interfaces:**
- Add `bool i2c_accel_vibration_hit(uint8_t sensitivity_level);` for one bounded sample result.
- Add `void i2c_accel_reset_vibration_window(void);` for clearing consecutive-hit state after a failed confirmation or mode transition.
- Keep existing `i2c_accel_read`, `i2c_accel_detect_vibration`, and `i2c_accel_is_moving` ABI behavior for unrelated callers.

- [ ] **Step 1: Extend tests** to assert level 10 maps through a named product-level threshold, samples are rate-limited to the existing 200 ms cadence, and a missed sample clears the work-mode confirmation window.
- [ ] **Step 2: Run the focused test and verify the new contract fails**.

Run: `python tools/tests/test_work_mode_policy.py`

Expected: FAIL on the new adapter assertions.

- [ ] **Step 3: Implement the adapter** without exposing DA218E raw values to `work_mode.c`; use a named level-to-threshold mapping with level 10 as the default and preserve I2C recovery/timeout behavior.
- [ ] **Step 4: Run the focused test and verify it passes**.

Run: `python tools/tests/test_work_mode_policy.py`

Expected: PASS.

### Task 3: Add Logical ACC and Complete Location-Report Hooks

**Files:**
- Modify: `include/jt808.h`
- Modify: `src/jt808.c`
- Create: `tools/tests/test_work_mode_jt808_contract.py`

**Interfaces:**
- Add `void jt808_set_logical_acc(bool on);` and `bool jt808_get_logical_acc(void);`.
- Add `int jt808_send_location_work_mode(uint32_t alarm_bits, bool historical_position);` which uses the current complete online `0x0200` extension builder and only changes the logical ACC/status and alarm bits requested by the work-mode layer.
- Keep `jt808_send_location`, `jt808_send_location_to`, and blind-zone APIs unchanged.

- [ ] **Step 1: Write failing source-contract tests** checking that the `0x0200` status builder reads the logical ACC override rather than PA12 directly, alarm bits are supplied by the new entry point, historical reports clear GPS-valid status, and the existing extension length/path remains selected.
- [ ] **Step 2: Run the contract test and verify it fails**.

Run: `python tools/tests/test_work_mode_jt808_contract.py`

Expected: FAIL because the new hooks are absent.

- [ ] **Step 3: Implement the narrow JT808 hooks** with static state, no new heap allocation, and no changes to blind-zone serialization. Ensure an alarm report retains the current logical ACC and does not force realtime mode.
- [ ] **Step 4: Run the contract test and verify it passes**.

Run: `python tools/tests/test_work_mode_jt808_contract.py`

Expected: PASS.

- [ ] **Step 5: Run existing JT808 location tests**.

Run: `python tools/tests/test_jt808_first_location.py; python tools/tests/test_jt808_registration_tx.py`

Expected: PASS.

### Task 4: Implement Online STOP1 Sleep Adapter

**Files:**
- Create: `include/work_mode_sleep.h`
- Create: `src/work_mode_sleep.c`
- Modify: `include/power_mgr.h`
- Modify: `src/power_mgr.c`
- Create: `tools/tests/test_work_mode_contract.py`

**Interfaces:**
- `typedef enum { WORK_SLEEP_WAKE_NONE = 0, WORK_SLEEP_WAKE_RTC = 1u << 0, WORK_SLEEP_WAKE_ACC = 1u << 1, WORK_SLEEP_WAKE_VIBRATION = 1u << 2, WORK_SLEEP_WAKE_SOS = 1u << 3, WORK_SLEEP_WAKE_POWER = 1u << 4 } work_sleep_wake_t;`
- `void work_mode_sleep_init(void);`
- `bool work_mode_sleep_ready(void);`
- `void work_mode_sleep_process(uint32_t next_service_ms, work_sleep_wake_t pending_wake);`
- `work_sleep_wake_t work_mode_sleep_take_wake(void);`
- `void work_mode_sleep_isr_wake(work_sleep_wake_t source);`
- `bool work_mode_sleep_is_in_stop1(void);`

- [ ] **Step 1: Write source-contract tests** requiring `PWR_EnterStopState(PWR_REGULATOR_LOWPOWER, PWR_STOPENTRY_WFI)`, RTC Alarm setup/clear, maximum 15-second slices, `hw_restore_after_stop2`-equivalent clock restoration before UART/DMA service, STOP1 admission guards for AT/TCP/Flash/FOTA, and shallow-sleep fallback on wake-path failure.
- [ ] **Step 2: Run the contract test and verify it fails**.

Run: `python tools/tests/test_work_mode_contract.py`

Expected: FAIL because the new adapter does not exist.

- [ ] **Step 3: Implement STOP1 entry/exit** using the SDK `PWR_EnterStopState` API, RTC Alarm A/`RTCAlarm_IRQn`, existing GPIO EXTI lines, and a 15-second maximum watchdog-safe segment. Restore clock/SysTick/UART/DMA before opening a bounded modem service window. Never power off EC800M or TCP.
- [ ] **Step 4: Replace the old power policy** in `power_mgr.c` with compatibility routing to the work-mode sleep adapter; remove hardcoded 120/300/600-second transitions and the old GPS-off/EC800M-PSM/deep-power-off behavior.
- [ ] **Step 5: Run the STOP1 contract test and verify it passes**.

Run: `python tools/tests/test_work_mode_contract.py`

Expected: PASS.

- [ ] **Step 6: Run the existing STOP2 regression to ensure unrelated low-power contracts remain visible**.

Run: `python tools/tests/test_power_stop2_contract.py`

Expected: PASS, or a narrowly documented update if the compatibility wrapper intentionally moves the old implementation and the test is adjusted to the new ownership boundary.

### Task 5: Configuration Defaults and Runtime Deadline Refresh

**Files:**
- Modify: `src/flash_config.c`
- Modify: `src/at_config.c`
- Modify: `include/flash_config.h` only if comments/ranges need correction
- Modify: `src/work_mode.c`
- Test: `tools/tests/test_work_mode_policy.py`

**Interfaces:**
- Add `void work_mode_config_changed(const device_config_t *cfg, uint32_t now_s);` as the single refresh hook called after an accepted SMS/F39/JT808 configuration update.

- [ ] **Step 1: Add failing assertions** for defaults 30/180/180 and immediate deadline recomputation after a `HEARTBEAT` or `TIMER=A,B` update.
- [ ] **Step 2: Run the focused test and verify it fails**.

Run: `python tools/tests/test_work_mode_policy.py`

Expected: FAIL on the current 60-second heartbeat/stopped defaults.

- [ ] **Step 3: Change only the configuration defaults and invoke the refresh hook** from existing successful configuration update paths; preserve range checks and Flash persistence transactions.
- [ ] **Step 4: Run the focused policy test and existing config tests**.

Run: `python tools/tests/test_work_mode_policy.py; python tools/tests/test_flash_config_migration.py; python tools/tests/test_f39_end_to_end.py`

Expected: PASS.

### Task 6: Integrate Main Loop, ACC Edges, Alarms, GPS, and JT808 Actions

**Files:**
- Modify: `src/main.c`
- Modify: `src/work_mode.c`
- Modify: `src/work_mode_sleep.c`
- Modify: `src/power_mgr.c` only for event-routing compatibility
- Modify: `Makefile`
- Modify: `include/config.h` only for named work-mode defaults if required by the existing configuration convention

**Interfaces:**
- `main.c` calls `work_mode_sleep_init()` and `work_mode_init()` after RTC/GPS/accelerometer/modem/JT808 initialization, then calls `work_mode_process()` once per bounded main-loop iteration.
- `work_mode_process()` consumes PA12 edge state, `i2c_accel_vibration_hit(10)`, `jt808` alarm latch, GPS validity, and RTC wake events; it drains actions by calling `gps_enable`, `jt808_set_logical_acc`, `jt808_send_location_work_mode`, and `jt808_send_heartbeat` through the adapter boundary.
- `scan_alarms()` calls `work_mode_notify_alarm(uint32_t alarm_bits)` through the main-loop event path; its ISR counterparts only set wake bits.

- [ ] **Step 1: Add a failing integration contract test** checking Makefile source inclusion, initialization order, PA12 high polarity, ACC falling-edge routing, SOS ISR wake routing, ADC-based power alarm detection, and absence of direct old `pwr_process` policy calls.
- [ ] **Step 2: Run the integration contract test and verify it fails**.

Run: `python tools/tests/test_work_mode_contract.py`

Expected: FAIL until the new sources and call sites are integrated.

- [ ] **Step 3: Add the two new sources to `Makefile` and initialize the work-mode layers** after `jt808_init`/`tcp_manager_init` have established their dependencies.
- [ ] **Step 4: Route main-loop events and action execution** so mode entry sends exactly one immediate `0x0200`, realtime uses `report_moving_s`, stationary sends independent `report_stopped_s` and `heartbeat_s`, simultaneous expiry emits two packets, and alarm-only reports return to STOP1 without changing state.
- [ ] **Step 5: Route ACC/G-sensor/SOS wake events** to the state machine and keep low-voltage/power-cut detection in bounded ADC service windows.
- [ ] **Step 6: Run the integration contract test and verify it passes**.

Run: `python tools/tests/test_work_mode_contract.py`

Expected: PASS.

### Task 7: Add Regression Guards and Build Verification

**Files:**
- Modify: `tools/tests/test_feature_guards.py` only if the new source files need release-input assertions.
- Modify: `tools/tests/test_power_stop2_contract.py` only if ownership moved and the assertion must target the compatibility boundary.
- Test: all new work-mode tests and existing low-power/JT808/config tests.

- [ ] **Step 1: Run all focused host tests**.

Run: `python tools/tests/test_work_mode_policy.py; python tools/tests/test_work_mode_contract.py; python tools/tests/test_work_mode_jt808_contract.py; python tools/tests/test_power_stop2_contract.py; python tools/tests/test_flash_config_migration.py; python tools/tests/test_jt808_first_location.py`

Expected: PASS.

- [ ] **Step 2: Build the firmware**.

Run: `make all`

Expected: successful `build/a300_firmware.hex` and size output without new compiler warnings treated as errors.

- [ ] **Step 3: Run memory and release guards**.

Run: `make ram-guard; make release-guard`

Expected: PASS; inspect map/RAM output for the new static queues and STOP1 context.

- [ ] **Step 4: Run diff hygiene checks**.

Run: `git diff --check; git status --short`

Expected: no whitespace errors; only intended work-mode files and existing user changes are present.

- [ ] **Step 5: Record hardware/HIL validation items** without claiming them complete: STOP1 current, RTC 15-second wake, IWDG stability, PA12/G-sensor/SOS wake, UART/DMA restore, TCP retention, GPS off/on, and 24-hour sleep/wake cycling.

## Plan Self-Review

- Spec coverage: policy states and priorities are Task 1; sensitivity-level vibration is Task 2; logical ACC and complete `0x0200` are Task 3; STOP1/TCP/RTC/fallback are Task 4; configurable defaults and runtime changes are Task 5; event ordering and alarm semantics are Task 6; automated/build verification is Task 7.
- Placeholder scan: completed successfully; no incomplete marker or unspecified implementation step is used. Each task names files, interfaces, failing test, implementation action, and verification command.
- Type consistency: all cross-task names are defined before use (`work_mode_*`, `work_mode_sleep_*`, `i2c_accel_vibration_hit`, `jt808_send_location_work_mode`).
- Scope check: no new protocol, Flash layout, third-party dependency, production deployment, or unrelated refactor is included.
