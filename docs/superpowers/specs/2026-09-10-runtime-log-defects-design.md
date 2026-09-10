# A300 V3.001 Runtime Log Defect Remediation Design

Date: 2026-09-10
Target: N32L406CBL7 A300-T9 firmware
Evidence: `ReceivedTofile-COM12-2026_9_10_16-52-25.TXT`

## Scope

Resolve the five runtime defects in this order:

1. Missing IMEI/ICCID after an MCU software reset.
2. False realtime entry from PA12 noise or stationary accelerometer spikes.
3. Runtime RAM/stack free gap below the 4096-byte release threshold.
4. NTP time shifted eight hours too far west.
5. NMEA sentence drops while blocking modem transactions run.

The work must preserve the current JT808 dual-session behavior, external Flash
formats, OTA contract, bounded retries, watchdog servicing, and the configured
five-minute boot-monitor policy. Unknown serial commands are excluded until a
reproducible command input is available.

## 1. Modem Identity Recovery

The modem state machine must not declare identity initialization complete when
IMEI or ICCID is empty or malformed. IMEI and ICCID queries use bounded retry
counters. Exhausting either counter moves the modem through its existing
bounded recovery/power-cycle path instead of advancing to network registration.
Successful software-reset startup must produce one valid identity-ready event
before READY, and both online JT808 channels must each send the boot `0x0107`
attributes exactly once.

Tests cover first-attempt success, transient query failure followed by success,
permanent IMEI failure, permanent ICCID failure, and software reset while the
modem remains powered. HIL acceptance requires valid masked identity lengths
and no `0x0107 unavailable` messages after software reset.

## 2. False Realtime Entry

PA12 must use continuous stable-level confirmation in both directions. A raw
edge or short pulse may keep the CPU awake for bounded confirmation but may not
change work mode, logical ACC, GNSS power, or emit an ACC entry report. The
confirmed-level interval is 500 ms; genuine ACC changes may therefore be
reported up to 500 ms later.

Accelerometer confirmation counts only samples whose measured delta actually
exceeds the configured threshold. A maximum of two isolated misses may keep an
existing episode alive, but misses are never converted into hits. Realtime
entry requires the configured number of genuine hits across the six-second
confirmation interval. Wake-window diagnostics count every sample exactly
once. Hardware motion interrupts may wake the CPU but do not by themselves
authorize realtime mode.

Tests cover sub-500 ms PA12 pulses, alternating PA12 noise, stable ACC ON/OFF,
single accelerometer spikes, sparse spikes, two missed samples during sustained
motion, three missed samples, and sustained motion confirmation. HIL acceptance
requires a stationary device to remain in sleep for at least 30 minutes with
no realtime transition while genuine ACC and sustained-vibration wake latency
remain within their configured bounds.

## 3. Runtime RAM And Stack Margin

Static SRAM consumers will be ranked from the linked ELF/map. Buffers with
non-overlapping lifetimes may share an existing bounded workspace only when
ownership is explicit and callers handle contention. Protocol limits, receive
bounds, persistent layouts, and recovery behavior must not be weakened.

The 4096-byte runtime free-gap threshold remains unchanged. Static map guards
must account for both reserved safety margin and measured/audited stack usage,
so a build cannot pass while the running image immediately reports `F=1`.
Host tests cover workspace ownership and guard arithmetic. HIL acceptance is
`F=0` and `RAM_GAP >= 4096` during boot, dual JT808 traffic, configuration,
SMS, and OTA preparation; the observed minimum is recorded.

## 4. NTP UTC Semantics

The raw `+QNTP` response contract is treated as the source of truth. Parsing
and conversion must apply the modem-reported time basis exactly once. The
result passed to `gps_apply_ntp_utc` is UTC; JT808 remains the only layer that
adds the configured local timezone when encoding a report.

Tests cover UTC+8, UTC-5, absent timezone suffix, and day/month/year rollover.
HIL acceptance compares the logged UTC value with a trusted clock and requires
an error no greater than two seconds, allowing serial transport latency.

## 5. GPS Receive Drops

The first remedy is to service pending GPS NMEA data during bounded blocking AT
wait loops without re-entering modem or application state machines. Increasing
the GPS queue is allowed only if drops remain and the RAM margin continues to
pass. ISR work remains limited to byte capture and sentence handoff.

Tests simulate NMEA arrival during AT waits and verify ordered parsing, bounded
work, watchdog feeds, queue overflow accounting, and no recursive modem calls.
HIL acceptance requires no increase in `DROP` during NTP, configuration query,
dual-channel reconnect, and OTA check operations.

## Verification And Delivery

Each defect follows RED, GREEN, focused regression, full firmware build,
release guard, RAM guard, and stack guard. Bootloader/App artifacts and the OTA
package are regenerated only after all five fixes pass. Final hardware claims
remain explicitly pending until cold boot, software reset, time comparison,
sleep/wake, and traffic stress are exercised on the target board.
