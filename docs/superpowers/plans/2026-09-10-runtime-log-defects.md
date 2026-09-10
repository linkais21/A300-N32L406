# A300 Runtime Log Defects Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct the five confirmed V3.001 runtime defects and produce a newly versioned full-flash image plus OTA package.

**Architecture:** Keep the existing cooperative main loop and state machines. Add bounded identity recovery, strengthen the two independent wake filters, consolidate only mutually exclusive SRAM buffers, correct the EC800M time contract, and service GPS through a narrow wait hook during blocking AT transactions.

**Tech Stack:** C99, ARM GNU Toolchain, N32L40x SPL, Make, Python host C harnesses.

## Global Constraints

- Preserve JT808 dual-session behavior, external Flash formats, OTA `a300-header-v1`, watchdog servicing, and the five-minute boot-monitor policy.
- PA12 requires 500 ms of continuous stability in both directions.
- Vibration misses may preserve an episode for at most two samples but never count as hits.
- Runtime `RAM_GAP` must remain at least 4096 bytes; do not lower the threshold.
- Do not reduce protocol bounds or remove recovery/error handling to recover SRAM.
- Do not commit, push, flash hardware, or overwrite V3.001 artifacts without explicit authorization.
- Every production edit follows a witnessed RED then GREEN cycle.

---

### Task 1: Recover Modem Identity After Software Reset

**Files:**
- Modify: `src/ec800m.c`
- Modify: `include/ec800m.h`
- Create: `tools/tests/test_ec800m_identity_recovery.py`
- Regression: `tools/tests/test_ec800m_urc_demux.py`
- Regression: `tools/tests/test_jt808_boot_terminal_info.py`

**Interfaces:**
- Produces: internal `identity_query_result_t` with `IDENTITY_QUERY_RETRY`, `IDENTITY_QUERY_READY`, and `IDENTITY_QUERY_RECOVER`.
- Produces for host tests: `ec800m_test_identity_retry(bool valid, uint8_t *attempts)`.
- Consumes: existing `ec800m_reset()`, `iccid_text_valid()`, IMEI 15-digit rule, and three-attempt bound.

- [ ] Write a host C harness proving transient IMEI/ICCID failures retry, success clears the counter, and the third failure returns RECOVER rather than READY.
- [ ] Run `python tools/tests/test_ec800m_identity_recovery.py`; expect failure because IMEI currently advances unconditionally and ICCID exhaustion advances to SIM/network registration.
- [ ] Add separate bounded IMEI and ICCID counters; clear identity buffers in `ec800m_init()` and `ec800m_reset()`; advance only after validated data; call the existing controlled modem reset on exhausted retries.
- [ ] Ensure `state_machine_sim()` cannot advance to network registration unless both identities remain valid.
- [ ] Run the new test and the two listed regressions; expect PASS.
- [ ] Run `make all` and inspect warnings; no commit.

### Task 2: Reject False ACC And Vibration Wakeups

**Files:**
- Modify: `include/work_mode.h`
- Modify: `src/work_mode.c`
- Modify: `src/i2c_accel.c`
- Modify: `src/main.c`
- Modify: `tools/tests/test_work_mode_policy.py`
- Create: `tools/tests/test_i2c_accel_vibration_filter.py`
- Regression: `tools/tests/test_two_mode_acc_stop1.py`
- Regression: `tools/tests/test_sleep_wake_timestamp_vibration_contract.py`

**Interfaces:**
- Produces: `WORK_MODE_ACC_DEBOUNCE_MS 500U`.
- Produces: `i2c_accel_vibration_hit()` returns only the current sample's threshold result.
- Consumes: `WORK_MODE_VIBRATION_MISS_TOLERANCE == 2U` in `process_vibration()`.

- [ ] Add policy cases for a 499 ms PA12 pulse, alternating noise, stable 500 ms ON/OFF, one spike, sparse spikes, two misses, three misses, and sustained true motion.
- [ ] Add an accelerometer harness showing a raw miss after one spike returns false; expect both test groups to fail against current behavior.
- [ ] Change PA12 confirmation to 500 ms without changing logical ACC until the stable candidate commits.
- [ ] Remove the one-second true-value extension from `i2c_accel_vibration_hit()`; retain raw episode diagnostics only.
- [ ] Implement the currently unused two-miss allowance in `work_mode.c`: misses preserve time/history, do not increment hits, and the third consecutive miss clears the episode.
- [ ] Remove the duplicate unconditional `++vibration_wake_samples` in `main.c` and verify every eligible sample increments once.
- [ ] Run all four focused test files; expect PASS.
- [ ] Run `make all`; no commit.

### Task 3: Restore A 4096-Byte Runtime RAM Gap

**Files:**
- Create: `include/agnss_stream_workspace.h`
- Create: `src/agnss_stream_workspace.c`
- Modify: `src/agnss_huada.c`
- Modify: `src/agnss_zhongkewei.c`
- Modify: `include/service_workspace.h`
- Modify: `src/service_workspace.c`
- Modify: `src/agnss_storage.c`
- Modify: `Makefile`
- Modify: `tools/map_ram_guard.py`
- Modify: `tools/tests/test_ram_guard.py`
- Create: `tools/tests/test_agnss_workspace_ownership.py`

**Interfaces:**
- Produces: one 4096-byte AGNSS parser workspace shared by mutually exclusive Huada and Zhongkewei parsers, with explicit acquire/release owner values.
- Extends: `service_workspace_owner_t` with `SERVICE_WORKSPACE_OWNER_AGNSS` and capacity 1024 bytes.
- Consumes: external-Flash ownership, which prevents AGNSS storage and OTA from using the service workspace concurrently.

- [ ] Add ownership tests proving the two vendor parsers cannot acquire simultaneously and AGNSS storage cannot overlap OTA/diagnostic use.
- [ ] Add RAM-guard fixtures that include an audited stack reserve in addition to static SRAM; expect failure with the current static-only arithmetic.
- [ ] Replace the separate 4096/2048-byte vendor parser arrays with the shared 4096-byte workspace; preserve parser reset on acquire/release.
- [ ] Move the 1024-byte AGNSS storage buffer into the enlarged service workspace and handle acquisition failure without retry loops.
- [ ] Update the build source list and make the guard require `static SRAM + audited stack peak + 4096 <= 24576`.
- [ ] Run workspace, AGNSS vendor/storage, RAM watermark, map guard, and stack guard tests; expect PASS.
- [ ] Run `make -B all`, `make ram-guard`, and `make stack-guard`; inspect the map and require at least 2560 bytes less static SRAM than V3.001.
- [ ] Record that `F=0` and actual `RAM_GAP >= 4096` still require HIL traffic stress; no commit.

### Task 4: Correct EC800M NTP UTC Conversion

**Files:**
- Modify: `src/ec800m.c`
- Modify: `tools/tests/test_ec800m_ntp_sync.py`
- Regression: `tools/tests/test_gps_ntp_apply.py`
- Regression: `tools/tests/test_ntp_resync_wiring.py`

**Interfaces:**
- Produces: parsed `ec800m_time_t` in UTC exactly once.
- Consumes: raw `+QNTP` response and leaves JT808 local-time adjustment in `jt808_apply_timezone()`.

- [ ] Add the observed UTC+8 case where the modem timestamp already represents UTC and the suffix must not cause a second subtraction; expect the current conversion test to fail.
- [ ] Preserve strict syntax/range validation and make the time-basis decision explicit in one conversion helper.
- [ ] Update rollover cases for positive, negative, and absent suffixes according to the verified EC800M contract.
- [ ] Run the three focused tests; expect PASS.
- [ ] Run `make all`; record that raw modem response and <=2-second UTC comparison require HIL; no commit.

### Task 5: Service GPS During Blocking AT Waits

**Files:**
- Modify: `include/ec800m.h`
- Modify: `src/ec800m.c`
- Modify: `src/main.c`
- Create: `tools/tests/test_ec800m_wait_service.py`
- Regression: `tools/tests/test_nmea_replay.py`
- Regression: `tools/tests/test_ec800m_ntp_sync.py`

**Interfaces:**
- Produces: weak `void ec800m_wait_service_hook(void)` in the modem driver.
- Produces: strong application implementation that calls only `gps_process()`.
- Constraint: hook is called inside bounded AT waits, may not call EC800M/JT808/FOTA state machines, and must not recurse into AT ownership.

- [ ] Add a host harness that injects NMEA while an AT response is delayed and proves the hook runs, watchdog continues, and the AT timeout remains bounded; expect failure because no hook exists.
- [ ] Invoke the hook in polling waits after watchdog servicing and provide the strong GPS-only application implementation.
- [ ] Run the new harness plus NMEA and NTP regressions; expect PASS.
- [ ] Run `make all`, RAM guard, and stack guard; require no new static buffer and no stack-limit regression.
- [ ] Record that zero `DROP` growth during NTP/reconnect/OTA checks requires HIL; no commit.

### Task 6: Full Regression And Versioned Artifacts

**Files:**
- Modify through existing generator: `include/build_version.h`
- Modify: `release_identity.json` only after all fixes pass, from V3.001/counter 3001 to V3.002/counter 3002.
- Generate: new versioned App-only, Bootloader, FULL, manifest, and OTA artifacts under `build/` without overwriting V3.001.

- [ ] Run every new focused test in task order, then all related `tools/tests/test_*.py` host tests.
- [ ] Run `make -B all`, Bootloader build, `make release-guard`, `make ram-guard`, `make stack-guard`, and `git diff --check`.
- [ ] Increment the revision from V3.001/counter 3001 to V3.002/counter 3002 and regenerate artifacts with `tools/build_dev_release.py`.
- [ ] Verify App and Bootloader vectors, FULL HEX-to-Combined BIN byte equality, OTA header/version/length/hash, and SHA-256 manifest entries.
- [ ] Report changed files, fresh command results, uncommitted status, and the required HIL matrix: cold boot, software reset, 30-minute stationary test, genuine ACC, genuine vibration, UTC comparison, dual-channel traffic, sleep/wake, and OTA preparation.
