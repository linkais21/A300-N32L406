# 0x8103 location and speed parameter repair (2026-09-16)

## Evidence and scope

The supplied COM8 log contains two `0x8103 result=3` replies but no parameter
IDs. The subsequently supplied packet contains this 37-byte body (identity
and transport header omitted):

```
04 00000029 04 0000001E 00000027 04 000000B4
   00000020 04 00000000 00000021 04 00000000
```

0x0029 and 0x0027 already update moving/stopped reporting intervals. Missing
0x0020 and 0x0021 table entries caused the entire transaction to be rejected.
The protocol source is the JT808-2013 Word document in the workspace protocol
directory, terminal parameter table. 0x0020=0 means periodic reporting;
0x0021=0 means ACC-based reporting. These are now accepted and returned as
DWORD zero in 0x0104. Other modes return result=3 without applying any item.
Incorrect wire length still returns result=2.

These are fixed supported capabilities, not newly persisted configuration.
Existing logical ACC, startup monitoring, vibration wake, sleep reporting
settings and GNSS validity rules still govern actual reports. There is no
new distance-based or driver-login reporting implementation.

0x0055 now reads/writes the existing speed_limit_kmh field as a DWORD in km/h.
Accepted range is 20..200, matching SPEED and the existing overspeed policy.
There is no Flash layout/version change. The active overspeed detector reads
this field directly; its existing 10-second persistence and 300-second
cooldown are unchanged. 0x0056 is not implemented by this repair.

The other ten IDs in the user's list already existed. A test now submits all
eleven together, checks exact query encoding, simulated reload, repeat-write
idempotence, malformed inputs and persistence failure with no live changes.

## Files touched

- include/jt808_params.h: fixed-mode parameter IDs.
- src/jt808_params.c: mode validation/query and speed configuration mapping.
- tools/tests/test_jt808_params.py: transaction, boundary and query regression.
- tools/tests/test_jt808_params_wire.py: actual RX/ACK/query on both channels,
  using the supplied location body and a synthetic terminal identity.
- This document.

## Verification

Run from the firmware repository with `python tools/tests/<name>.py`:

| Test | Result |
| --- | --- |
| test_jt808_params | RED before implementation at mixed transaction success assertion; GREEN after |
| test_jt808_params_wire | PASS |
| test_overspeed_policy | PASS |
| test_work_mode_policy | PASS |
| test_work_mode_jt808_contract | PASS |
| test_flash_config_v3 | PASS, including NOR power-cut cases |
| test_flash_config_migration | PASS |
| test_feature_guards | PASS |

`make` was absent from PATH; installed `mingw32-make` was used instead:

- `mingw32-make all BUILD=build-params-20260916`: PASS. Flash 105176/106496
  bytes, 1320 bytes remaining; LOW_HEADROOM and CONFIGURATION_CHANGED alerts.
  Baseline is not comparable, so no size-reduction claim is made.
- `mingw32-make ram-guard BUILD=build-params-20260916`: FAIL. Whole-program
  stack evidence remains incomplete (90 missing frames, 55 indirect transfers,
  116 tail transfers, one cycle). Static RAM 17884 bytes; known call frames
  2504 bytes. This is not a release-qualified build.
- `git diff --check -- src/jt808_params.c include/jt808_params.h`: PASS,
  with Git CRLF conversion notices only.

Build output is isolated; existing release artifacts and version identity
were not overwritten. No commit, deployment or device flashing was performed.

## Required device/HIL checks

Needs real-device/HIL verification: resend the supplied location packet,
check success ACK and 0x8106/0x8104 values, reboot and query intervals again;
observe 30-second active and 180-second stopped reporting under the existing
work-mode rules and valid GNSS conditions. Set 0x0055, reboot/query it, and
verify controlled overspeed alarm timing, recovery and cooldown. Confirm
unsupported modes and out-of-range limits leave all settings unchanged.
