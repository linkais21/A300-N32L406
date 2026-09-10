# SMS Runtime Closure Design

## Objective

Make every supported F39 SMS setting affect the running N32L406 firmware, not
only the persisted configuration. The immediate field failures are
`FREQ,10,180#` producing apparent five-second traffic and a configured `FIP`
channel authenticating without receiving `0x0200` reports.

## Root Cause and Architecture

The EC800M send-result wait currently searches its response with C string
functions. A binary byte before `SEND OK` terminates that search, so a frame
which the platform receives and acknowledges is reported as an ambiguous
failure after five seconds. This leaves per-channel first-fix state pending,
blocks the second channel until its snapshot is stale, and creates repeated
traffic. The response matcher will become length-aware while preserving SMS
and socket URC demultiplexing.

`work_mode` remains the sole periodic `0x0200` scheduler. JT808 owns framing
and broadcasts a work-mode report to every authenticated channel. A channel
which newly authenticates independently receives one fresh first-fix report.
The legacy JT808 timer retains corner-report and per-channel first-fix duties,
but no longer emits a second ordinary periodic report.

## SMS Runtime Semantics

- `FREQ`: update moving/stopped deadlines immediately and enable stationary
  location reporting, matching the G452 behavior. `GPSDUP,0` may explicitly
  disable it afterwards.
- `FIP`/`IP`: reconnect both configured links; each link keeps independent
  registration/authentication state and receives normal location/heartbeat
  traffic once online.
- `MODEL`/`CAR`/`PID`: refresh the in-memory JT808 registration identity before
  forcing re-registration.
- `APN`: reconnect the modem data session so the persisted APN is used.
- `GPSDUP`: immediately enable or suppress stationary `0x0200`; heartbeats
  continue in both modes.
- `SPEED`: apply the configured 20-200 km/h threshold to a bounded overspeed
  alarm state machine.
- `GMTSET`: use the configured signed offset when encoding JT808 time rather
  than a hard-coded UTC+8 conversion.
- `MLG`, `GPSBDS`, `VIBSENS`, `RELAY`, `HBT`, and queries keep their existing
  live behavior, with regression coverage proving their consumer path.

## Verification

Host tests must reproduce the binary-before-`SEND OK` response, the ten-second
single scheduler, dual-channel `0x0200`, per-channel first fix, sleep-report
toggle, runtime identity refresh, configured timezone, APN reconnect, and
overspeed alarm. Then run the relevant host regression set, `make all`, release
and RAM guards, and inspect `git diff --check`. Hardware SMS, real PDP/APN,
dual-platform delivery and alarm behavior remain explicit HIL checks.
