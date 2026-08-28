# Task7-F39 Execution Design

## 1. Objective and migration boundary

Implement the approved A300 SMS command behavior in A300_406 so every command admitted by the F39 whitelist performs a real, testable action or query.

This is a functional migration, not a whole-project copy. The A300 source at `D:\A300_Tools\A300-N32G452\A300-N32G452\app` is the behavioral reference for command grammar, validation, replies, persistence and runtime side effects. N32G452 startup files, SDK, linker scripts, clock/interrupt code, peripheral drivers, build files and removed product customizations must not be copied into A300_406.

## 2. Architecture

The existing bounded SMS transport remains unchanged:

```text
EC800M +CMT URC
  -> two-entry sender+command FIFO (192-byte command bound)
  -> strict F39 whitelist
  -> f39_command adapter
  -> A300_406 service/config interfaces
  -> one result object
  -> bounded SMS response
```

`f39_command` owns SMS grammar and maps it to platform-neutral operations. It must not call N32G452 registers or SDK APIs. `at_config` may dispatch an approved SMS command to `f39_command`, but the F39 implementation is separate from the debug-serial `CMD=...` grammar.

## 3. Approved commands

The source of truth is `D:\A300_406_tools\文档\1_定位终端指令说明V1.0.xlsx`, constrained by the approved feature trimming. Retain:

- `PARAM`
- `DUALSET`
- `RESET`
- `PID`
- `IP`
- `FIP`
- `FREQ`
- `HBT`
- `MODEL`
- `SPEED`
- `APN`
- `RELAY`
- `GPSDUP`
- `MLG`
- `CAR`
- `GPSBDS`
- `GMTSET`

Do not restore `VIBSENS`, `CANCEL`, `DISMODE`, `POWERMODE`, `VELOCITY`, Baler, CMCC, RTK/NTRIP, LBS, C21/BK, TTS or other removed commands.

## 4. Command execution model

Every command passes through these stages:

1. Bounded parse with exact delimiters and no trailing garbage.
2. Range, character-set, state and authorization checks.
3. Build a candidate configuration or action descriptor without side effects.
4. Commit configuration once, then apply runtime side effects.
5. Produce a bounded success or failure response associated with the original sender.

Queries never modify state. Set commands must not report success until persistence succeeds. Immediate actions such as reset and relay are explicit operations and cannot appear inside `DUALSET`.

## 5. DUALSET atomic transaction

`DUALSET` is atomic:

- Parse all `*`-separated subcommands first.
- Allow only configuration subcommands from `IP`, `FIP`, `FREQ`, `HBT`, `MODEL`, `SPEED`, `APN`, `GPSDUP`, `MLG`, `CAR`, `GPSBDS`, and `GMTSET`.
- Reject nested `DUALSET`, `RESET`, `RELAY`, empty items, duplicate keys, malformed delimiters and unsupported commands.
- Clone the current configuration into a candidate value and apply all subcommands to that candidate only.
- If any validation fails, discard the candidate without persistence, reconnect, GNSS command or other side effect.
- If all items validate, persist the candidate once. If persistence fails, keep the previous configuration and return failure.
- After persistence succeeds, apply the accumulated side effects once in deterministic order: report timers, network reconnect, GNSS mode, then other runtime refreshes.

## 6. Command mappings

- `IP`/`FIP`: main/backup host and port; validate host length 1-63 and port 1-65535. `FIP,0` disables backup. Successful changes schedule bounded reconnect after commit.
- `FREQ`: moving 1-300 seconds and stopped 5-65535 seconds; update JT808 reporting timers after commit.
- `HBT`: 30-3600 seconds.
- `MODEL`: 1-20 visible ASCII characters excluding comma and `#`; schedule JT808 re-registration.
- `SPEED`: 20-200 km/h.
- `APN`: APN/user/password fields at most 31 characters; `AUTO` or `0` restores automatic APN; reconnect after commit.
- `RELAY`: accept `0`, `1`, or query. Cutting power requires valid positioning and speed below 20 km/h; restore is always allowed.
- `GPSDUP`: `0` or `1` controls sleep-period positioning reports.
- `MLG`: non-negative mileage in 0.1 km units within the persisted field range.
- `CAR`: preserve the workbook province-code mapping and bounded plate storage.
- `GPSBDS`: only modes 1 GPS, 2 BDS, and 3 GPS+BDS; dispatch only receiver commands supported by TAU804M or ATGM332D-F7N after persistence.
- `GMTSET`: parse `Ehhmm`/`Whhmm`, validate hour/minute ranges and store signed offset.
- `PID`: query/set the JT808 terminal identifier using the A300 contract, with strict numeric/length validation chosen from the current production format.
- `PARAM`: return the reduced F09/F19 identity, version, network, GNSS, server, timing, ACC and APN fields; response construction must be bounded and may split into multiple SMS messages if one SMS is insufficient.
- `RESET`: return success, then schedule a bounded delayed reset so the response can be transmitted first.

## 7. Replies and failures

Responses follow the workbook command name and explicit `Success!` or bounded error classification. Errors distinguish unsupported, malformed, range/state, persistence and busy failures without exposing credentials. Response buffers are statically allocated and capped; each response remains associated with its FIFO sender.

## 8. Safety and persistence

- No dynamic allocation or unbounded waits/copies.
- OTA retains priority. Configuration changes that require Flash or modem ownership fail or defer boundedly while OTA owns the resource.
- `DUALSET` performs one persistence transaction.
- Reset occurs only after response handoff.
- Relay safety constraints cannot be bypassed by SMS or `DUALSET`.
- SMS credentials and APN passwords are never returned by `PARAM` or logs.

## 9. Verification

Host C harnesses must verify every approved query/set grammar, range boundaries, persistence failure, side-effect ordering, reply association and removed-command rejection. `DUALSET` tests must prove no partial state or side effect after a late failing subcommand, exactly one save after success, duplicate/nested/action rejection and deterministic post-commit effects.

At least one end-to-end harness covers `+CMT -> FIFO -> F39 execution -> config/action -> reply`. Target ARM build, map/SRAM gate and hardware verification remain Task10 release gates and must not be claimed from host tests.
