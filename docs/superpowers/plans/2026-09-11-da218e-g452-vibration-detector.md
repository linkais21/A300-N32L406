# DA218E G452 Vibration Detector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the proven G452 max-axis, 1/8 EMA vibration detector to N32L406 without changing the L406 hardware driver, sensitivity mapping, or six-second work-mode policy.

**Architecture:** Add a portable `accel_vibration_filter` unit that owns only the baseline and motion calculation. `i2c_accel.c` supplies DA218E samples and the existing threshold, while `work_mode.c` continues to own six-second confirmation and mode transitions unchanged.

**Tech Stack:** C99, ARM GNU Toolchain, Python host-test runner, native host C compiler, Make.

## Global Constraints

- Keep the N32L406 hardware I2C transactions, address probing, and DA218E register configuration unchanged.
- Keep `i2c_accel_vibration_hit(uint8_t)`, diagnostics, `VIBSENS` 1..50 mapping, 200 ms cadence, and the six-second `work_mode` policy unchanged.
- Do not modify G452 reference files, STOP1/shallow-sleep selection, ACC, GNSS, EC800M, JT808, or firmware artifacts.
- Preserve all pre-existing dirty-worktree changes and do not create commits without explicit user authorization.
- Hardware behavior remains subject to real-device/HIL verification.

---

### Task 1: Portable G452 Vibration Filter And Regression

**Files:**
- Create: `include/accel_vibration_filter.h`
- Create: `src/accel_vibration_filter.c`
- Create: `tools/tests/test_accel_vibration_filter.py`
- Modify: `src/i2c_accel.c:88-123,382-413,417-500`
- Modify: `Makefile:29-57`

**Interfaces:**
- Consumes: signed DA218E XYZ samples and the existing `uint16_t` threshold.
- Produces: `void accel_vibration_filter_reset(accel_vibration_filter_t *filter)` and `bool accel_vibration_filter_step(accel_vibration_filter_t *filter, int16_t x, int16_t y, int16_t z, uint16_t threshold, uint16_t *motion)`.

- [x] **Step 1: Write the failing host test**

Create a Python runner that compiles a C harness with `src/accel_vibration_filter.c` and `src/work_mode.c`. The harness must assert these exact behaviors:

```c
accel_vibration_filter_t filter;
uint16_t motion;

accel_vibration_filter_reset(&filter);
assert(!accel_vibration_filter_step(&filter, 0, 0, 0, 150U, &motion));
assert(!accel_vibration_filter_step(&filter, 100, 100, 100, 150U, &motion));
assert(motion == 100U); /* max axis, not the old sum of 300 */

accel_vibration_filter_reset(&filter);
assert(!accel_vibration_filter_step(&filter, 0, 0, 0, 150U, &motion));
assert(accel_vibration_filter_step(&filter, 200, 0, 0, 150U, &motion));
assert(motion == 200U);
```

Add an end-to-end filter plus `work_mode` case that seeds a zero baseline, feeds the stationary `(-40, 10, 1000)` vector every 200 ms for more than six seconds, and asserts the state remains `WORK_MODE_STATIONARY_SLEEP`. Add a second case with alternating Z samples around the baseline for six seconds and assert the state becomes `WORK_MODE_REALTIME`.

- [x] **Step 2: Run the new test and verify RED**

Run: `python tools/tests/test_accel_vibration_filter.py`

Expected: FAIL because `accel_vibration_filter.h` and `src/accel_vibration_filter.c` do not exist. This confirms the new behavior is not yet implemented.

- [x] **Step 3: Implement the minimal portable filter**

Define the filter state without hardware dependencies:

```c
typedef struct {
    int32_t baseline_x;
    int32_t baseline_y;
    int32_t baseline_z;
    bool initialized;
} accel_vibration_filter_t;
```

Implement the G452 order exactly: seed the first sample, compute absolute X/Y/Z deviation from the update-before baseline, select the maximum axis, compare it with `threshold`, then adapt all three baselines by `difference >> 3`. Store the maximum-axis value through `motion`; never use a three-axis sum.

- [x] **Step 4: Integrate the filter with the L406 adapter**

Replace both private EMA implementations in `i2c_accel.c` with independent `accel_vibration_filter_t` instances. `i2c_accel_reset_vibration_window()` resets only the work-mode filter. `i2c_accel_vibration_hit()` continues to update `s_diag`, count hits, and rate-limit logs, but sets `s_diag.delta` to the filter's maximum-axis motion. Keep the existing threshold mapping and sample cadence unchanged.

Add `src/accel_vibration_filter.c` beside `src/i2c_accel.c` in `C_SRCS`; do not reorder or rewrite unrelated Makefile entries.

- [x] **Step 5: Run the new test and verify GREEN**

Run: `python tools/tests/test_accel_vibration_filter.py`

Expected: all max-axis, recovery, sustained-motion, and six-second integration cases PASS with `-std=c99 -Wall -Wextra -Werror`.

- [x] **Step 6: Run focused existing regressions**

Run each command independently:

```powershell
python tools/tests/test_i2c_accel_vibration_adapter.py
python tools/tests/test_vibration_wake_optimization.py
python tools/tests/test_work_mode_policy.py
python tools/tests/test_sleep_wake_timestamp_vibration_contract.py
python tools/tests/test_da218e_i2c_contract.py
```

Expected: all PASS. Any source-contract assertion that still describes the old sum/1/32 algorithm must be updated only after verifying that it conflicts with the approved design.

### Task 2: Firmware Build And Release Guards

**Files:**
- Verify: `build/a300_firmware.elf`
- Verify: `build/a300_firmware.hex`
- Verify: `build/a300_firmware.map`
- Review: all files changed by Task 1

**Interfaces:**
- Consumes: the integrated filter from Task 1 through `i2c_accel.c`.
- Produces: a buildable N32L406 image and fresh host/build evidence; no release artifact overwrite, flash, commit, push, or deployment.

- [x] **Step 1: Build the firmware**

Run: `make all`

Expected: ARM compile and link succeed with no new compiler errors or warnings, and the memory report remains within the configured Flash and RAM limits.

- [x] **Step 2: Run memory and release gates**

Run each command independently:

```powershell
make ram-guard
make release-guard
make stack-guard
```

Expected: each command exits zero. Report the first genuine failure without hiding it behind a later successful command.

- [x] **Step 3: Inspect the final scope**

Run:

```powershell
git diff --check
git diff -- Makefile include/accel_vibration_filter.h src/accel_vibration_filter.c src/i2c_accel.c tools/tests/test_accel_vibration_filter.py
git status --short
```

Expected: no whitespace errors, no secrets/debug leftovers, no G452 changes, and no unrelated user changes attributed to this task.

- [ ] **Step 4: Record HIL acceptance items**

Require a fresh static-device capture for at least two sleep cycles. Acceptance is no unexpected `SLEEP->REALTIME ... vib=1`; a controlled sustained vibration must still produce one transition after at least six seconds. Mark this as `需要实机/HIL验证` until the capture is supplied.

Status: `需要实机/HIL验证`.
