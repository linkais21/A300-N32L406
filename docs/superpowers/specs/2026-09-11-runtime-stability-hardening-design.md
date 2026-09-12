# A300 Runtime Stability Hardening Design

## Goal

Improve runtime fault diagnosis, modem identity recovery, mileage persistence
endurance, and DA218E INT1 latch handling without changing the validated
shallow-sleep profile or normal JT808 reporting behavior.

## Scope

This change covers four bounded areas:

1. Preserve the last main-loop phase and fault context across an IWDG reset.
2. Prevent TCP/JT808 startup while EC800M IMEI or ICCID is unavailable, and
   recover identity with bounded retries.
3. Remove per-GNSS-update configuration-sector erases caused by mileage
   accumulation.
4. Clear and verify the DA218E INT1 latch at initialization and after a
   consumed vibration window.

The following behavior remains unchanged:

- `A300_STOP1_SLEEP=0` and the `shallow` sleep profile.
- JT808 0x0200 retained-position timestamp behavior in a no-fix environment.
- The five-minute boot monitor and its logical ACC policy.
- Hardware pin assignments, DA218E address probing, JT808 message formats,
  FOTA layout, and external Flash partition addresses.

## 1. Watchdog And Fault Diagnostics

### Evidence

The field log contains an IWDG reset after otherwise normal modem, GNSS,
accelerometer, and RAM diagnostics. Existing reset diagnostics report only the
reset source, so they cannot distinguish a blocked subsystem from a HardFault
that deliberately waits for IWDG recovery.

### Design

Reserve a small group of currently unused RTC backup registers for a versioned
runtime diagnostic record. The record contains:

- magic and format version;
- last main-loop phase;
- monotonically increasing loop sequence;
- fault marker;
- stacked PC and LR when available;
- SCB `CFSR` and `HFSR` values.

The main loop writes only memory-mapped RTC backup registers before each major
service boundary. It never writes internal or external Flash and never waits
for a peripheral response. The phase list distinguishes EC800M, GPS, mileage,
TCP manager, JT808, monitoring, FOTA, configuration, AGNSS, work mode, command
processing, alarms, NTP, status logging, and shallow WFI.

On boot, reset diagnostics validate the record using its magic/version and
print it only for IWDG, WWDG, or fault-related recovery. The record is then
re-armed for the new boot. Invalid or uninitialized backup data is ignored.

HardFault handling captures the stacked PC/LR and SCB status before retaining
the existing fail-closed behavior. It does not attempt Flash writes, complex
formatting, dynamic allocation, or recovery inside the exception.

This instrumentation identifies the next failure location; it does not hide a
blocked subsystem by feeding the watchdog indefinitely.

## 2. EC800M Identity Recovery

### Evidence

After the IWDG reset, the log shows EC800M READY with empty IMEI/ICCID. TCP and
JT808 authentication continue because the configured PID is valid, while every
0x0107 terminal-attributes upload fails because ICCID is absent. This violates
the intended EC800M state-machine invariant that identity is valid before
network registration.

### Design

Expose a read-only `ec800m_identity_ready()` predicate using the existing exact
IMEI and ICCID validators.

Enforce the invariant at two boundaries:

- EC800M READY processing detects invalid identity and transitions to a bounded
  identity-refresh path beginning at IMEI query step 6.
- TCP manager remains in `CS_WAIT_MODEM` until both `ec800m_is_ready()` and
  `ec800m_identity_ready()` are true.

Identity refresh clears only the identity-query attempt counters and local
socket state needed for reconnect. It does not erase PID, authentication code,
server configuration, mileage, or other persisted settings. Each query keeps
the existing timeout and three-attempt limit. Exhaustion uses the existing
bounded modem reset path; no infinite retry loop is introduced.

Once identity is valid, normal dual-channel connection, authentication, 0x0107
upload, and 0x0200 reporting resume without a manual reboot.

## 3. Mileage Persistence Endurance

### Evidence

`mileage_update()` currently calls `cfg_add_mileage()` for each accepted GNSS
distance. `cfg_add_mileage()` immediately saves the full configuration, and a
save erases one 4 KiB configuration sector. During normal driving this can
approach one erase per GNSS update.

### Design

Split mileage update from mileage persistence:

- Accepted distance immediately updates the in-RAM `mileage_m`, so JT808 and
  local queries continue to see the current value.
- Mileage becomes dirty without erasing Flash.
- While moving, dirty mileage is persisted no more than once per 10 minutes.
- Entering stationary sleep or detecting vehicle-power loss forces a save.
- A failed save keeps mileage dirty and retries only after a bounded backoff;
  it never busy-retries in the main loop.

Only the mileage path uses deferred persistence. Server, authentication,
security, and user configuration setters retain their immediate transactional
save behavior.

The first accepted GNSS point remains a baseline and adds no distance. Existing
stop-drift and per-update distance sanity checks remain unchanged. This task
does not recalibrate the GPS drift threshold.

The worst case for a sudden complete power loss is the mileage accumulated
since the last successful periodic save. A normal vehicle-power-loss event or
transition to stationary sleep forces a save before that interval expires.

## 4. DA218E INT1 Latch Handling

### Evidence

The log shows DA218E INT1 low before sensor setup and high throughout long
stationary periods. The current worktree already configures a single-event
latch and bounded software re-arm, but initialization does not perform a final
re-arm after all motion registers have been programmed.

### Design

After DA218E motion configuration completes, reset the interrupt latch once and
sample PB3. A high level after re-arm is recorded in diagnostics but does not
authorize a REALTIME transition.

After a vibration confirmation window is consumed, perform one bounded re-arm.
Retry at most three times on later main-loop passes. If all attempts fail,
remain in shallow polling mode and report a rate-limited diagnostic. Do not
block the main loop, repeatedly reset the latch every millisecond, or treat the
PB3 level alone as confirmed motion.

The existing six-second software confirmation and two-thirds hit requirement
remain the only authority for `SLEEP -> REALTIME` vibration transitions.

## Error Handling

- Backup diagnostic corruption is ignored and cannot prevent boot.
- Identity refresh is bounded by existing AT timeouts and reset limits.
- Mileage save failure preserves the RAM value and dirty flag for later retry.
- INT1 re-arm failure degrades to shallow polling and never disables motion
  detection.
- No new ISR performs Flash access, AT processing, logging, or unbounded work.

## Automated Verification

Add RED-to-GREEN host tests for:

- valid, invalid, and fault-marked backup diagnostic records;
- phase preservation across simulated IWDG reset;
- READY with missing IMEI/ICCID returning to identity refresh;
- TCP connection remaining blocked until identity is valid;
- successful recovery resuming connection and 0x0107 upload;
- hundreds of one-second mileage updates causing no configuration save;
- ten-minute periodic mileage save, forced sleep/power-loss save, save failure
  backoff, and no duplicate distance;
- startup INT1 re-arm, one re-arm per consumed window, bounded retry, and
  shallow-polling fallback;
- unchanged work-mode vibration confirmation and shallow-sleep contracts.

Run the relevant host suites, `make all`, `make release-guard`,
`make ram-guard`, and `git diff --check` before delivery.

## HIL Verification

The following claims require real-device/HIL validation:

1. RTC backup registers retain diagnostics across IWDG reset and do not disturb
   the RTC or shallow sleep.
2. A live EC800M after MCU-only reset has its identity re-read before TCP
   connection and resumes both JT808 channels.
3. A long drive produces bounded configuration generations while mileage stays
   current and is saved on ACC-off/power-loss.
4. DA218E INT1 returns low after re-arm when stationary, reasserts on motion,
   and sustained vibration still wakes after the six-second confirmation.
5. A multi-hour vibration/no-fix run produces no unexpected reset; if it does,
   the next boot prints a valid phase/fault record.
