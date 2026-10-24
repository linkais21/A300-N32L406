# Stationary mileage repair - 2026-10-12

## Report evidence

Read the user-supplied history workbook with openpyxl in read-only/data-only
mode. The original workbook was not saved or modified. Do not reproduce the
terminal identifier, address or coordinates in this document.

- Track sheet: 672 records, 2026-10-10 12:00:09 through 14:08:40.
- All reported driving speeds are 0.00 km/h.
- 671 records have ACC on, a valid fix and identical reported coordinates.
- Row 538, satellite time 13:28:47: displayed total mileage changes from
  4.60 km to 4.70 km while coordinates, zero speed and ACC-on status persist.
- Only the final record changes coordinates and has ACC off / no fix.
- The export is rounded and contains no raw NMEA or firmware identity. It
  proves the reported inconsistency, not the exact internal metre increment
  or the firmware revision running on that historical device.

## Reproduced source defect and correction

JT808 live positions use gps_report_filter_copy(), but mileage_update() used
raw GNSS coordinates. Its old distance filter rejected speed <2 km/h only
when raw displacement was below stopdrift_thr / 10 metres (default 5 m).
Larger stationary drift therefore accumulated mileage behind a fixed live
position and zero reported speed.

mileage_update() now uses the same live stationary decision. A selected
stationary anchor causes an immediate return and invalidates the old mileage
baseline. The first released valid fix seeds a new baseline; only subsequent
accepted displacement accumulates. Parking drift and the displacement from a
locked anchor to a released raw fix are never backfilled.

This decision is independent of ACC and sleep mode. Existing stopdrift
configuration, motion confirmation and sensor/fix freshness rules remain in
force. New locks still require the existing 30-second stable candidate,
<=1 km/h, fresh good-quality GNSS and concentrated coordinates. An established
lock can suppress weak <=3 km/h observations; genuine motion still releases
it under the existing rules. The change does not freeze all physical stops
before that evidence exists or when the filter is disabled/invalidated.

Touched files:

- src/mileage.c: share the live stationary decision and discard drift baseline.
- tools/tests/test_stationary_mileage.py: compile both real production modules.
- tools/tests/test_gps_report_wire.py: integrate the real odometer and assert
  unchanged 0x01 mileage, zero speed and fixed coordinates on both channels.
- tools/tests/test_mileage_persistence.py: provide an unlocked filter stub for
  existing persistence/math fixtures; real lock behavior is tested separately.
- This document.

## Validation

RED: the new real-C regression failed on the original source at the first
stationary drift mileage assertion, after confirming the report was locked.
GREEN: the same regression passes after the correction. It covers two hours
of simulated awake stationary drift, zero/small speed, weak 2.5 km/h evidence,
repeated main-loop calls, invalid-fix recovery, confirmed movement without
drift backfill, and mileage persistence after movement.

All following commands exited 0 on the final source:

```powershell
python tools/tests/test_stationary_mileage.py
python tools/tests/test_gps_report_filter.py
python tools/tests/test_gps_report_wire.py
python tools/tests/test_mileage_persistence.py
python tools/tests/test_mileage_quantization.py
python tools/tests/test_adc_power_loss_mileage.py
python tools/tests/test_feature_guards.py
mingw32-make.exe build-stationary-mileage-20261012/a300_firmware.hex size flash-guard BUILD=build-stationary-mileage-20261012
mingw32-make.exe release-gate BUILD=build-stationary-mileage-20261012
git diff --check
```

Build uses ARM GNU Toolchain 14.3.rel1 and the production Makefile, writing
only an isolated build directory. Initial `all` refreshed version metadata;
those generated changes were restored and the final candidate rebuilt using
explicit targets. No version allocation, release package or flashing occurred.
Logs and final input/artifact hashes are in
`build-stationary-mileage-20261012/validation/`.

Flash gate passes at 105564 / 106496 bytes (932 bytes remaining), with
LOW_HEADROOM and CONFIGURATION_CHANGED alerts; the recorded baseline is not
comparable. RAM gate passes with a 4104-byte runtime gap against its required
4096 bytes. The stack report still says INCOMPLETE (3 missing frames, 1 indirect
transfer and other unresolved transfers); these gates do not prove a complete
whole-program stack/heap/exception bound. No resource-safety claim beyond the
reported gates is made.

## Required bench / HIL verification

Hardware behavior needs real-device/HIL verification. Keep the device awake
with ACC on and stopdrift enabled. After the existing stationary lock forms,
observe for at least two hours: live speed stays zero, coordinates remain
fixed, the internal metre counter and the JT808 0x01 mileage do not increase,
and no mileage-only persistence write is scheduled. Include weak GNSS,
small-speed noise, sensor vibration and short GNSS loss. Then drive/creep to
confirm normal unlock and live reporting, with no jump charging parking drift.
Also check ACC-off/wake and reboot recovery under the existing filter rules.
No device was flashed or controlled during this task.
