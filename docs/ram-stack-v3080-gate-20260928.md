# V3.080 RAM/stack software gate and HIL handoff

Status: software gate passed; dedicated-device HIL pending. This is not a
production release approval.

## Exact candidate

- Identity: `T360-A300_406_20260928172551,V3.080`, counter `3080`.
- Build: `build-ram-hil-v3080`; test package:
  `artifacts/A300-406-V3.080-RAM-HIL-TEST-ONLY-20260928`.
- Source input SHA-256: `6b56a004354694ed66722916079192026a00b70693c54467c510dc39f75b12fc`.
  The digest is SHA-256 of each sorted relative path followed by a NUL byte and
  its file bytes. Inputs are all files under `src`, `include`, `ldscript`,
  `third_party/micro-ecc`, `sdk/Nations.N32L40x_Library.2.2.0/firmware`, and
  `bootloader/src`, plus `Makefile`, `release_identity.json`, and the four gate
  tools `exception_stack_guard.py`, `map_ram_guard.py`, `stack_usage_guard.py`,
  and `release_guard.py`.
- ELF SHA-256: `c9fec000ac915cf44fe0410708e71a073e5bf2947920cfe54e7a588e5c5a0e14`.
- MAP SHA-256: `5c717e15b57e5779858fc600eb1500f22faf6af38e5d8d877fc43233b986b59a`.
- App SHA-256: `47b036c19c96d4a78e59af6fe9914f9a5a3fbccec0fde7d181590ac120027cdd`.
- OTA SHA-256: `2a3001db486d4d26e8ba6f4710faec715d6f84d57b798702ad8fccb3e559d80b`.

## Software checks

- `mingw32-make BUILD=build-ram-hil-v3080 all`: passed.
- `mingw32-make BUILD=build-ram-hil-v3080 release-gate`: passed.
- Static SRAM 15960 B + linker alignment 4 B + hard heap 1024 B + maximum
  reviewed boot/main call chain 2852 B + five nested exception levels 580 B
  leaves 4156 B, exceeding the required 4096 B by 60 B.
- Flash load span 105356/106496 B, leaving 1140 B. The capacity check passes
  with low-headroom and changed-configuration alerts.
- Final-ELF printf, libgcc internal-call and startup proofs, the RAM budget
  negative tests, release identity, AGNSS, FOTA power-cut/recovery, F39/SMS and
  OTA format host regressions passed.
- The standalone `stack-analysis.json` has status `incomplete` because it
  reports unreachable auxiliary functions and does not include heap or
  exception costs. `ram-budget.json` is the release decision and checks that
  all reviewed execution roots have complete frames and targets.
- The source hash binds the reviewed Bootloader jump implementation. The
  current `bootloader/build/bootloader.bin` and the V3.078 package Bootloader
  match at SHA-256
  `2a79d31ba649408b2d75308601f6148487d3decde755899848d7f5c07b34e260`.
  The Bootloader actually installed on the HIL device has not been identified.

## Dedicated-device HIL still required

1. Upload only `OTA-A300-406-V3080-HIL.bin` to the test FOTA platform as
   model `A300-406`, version code `3080`; the platform supplies its detached
   signature. Keep V3.078 recovery available and avoid a fleet campaign.
2. Capture complete serial logs for normal OTA, power interruption/recovery,
   network interruption/recovery, F39/SMS load, AGNSS injection and several
   post-upgrade HEALTH reports. Confirm the V3.080 boot identity and FOTA trial
   to ACTIVE/LKG result for this exact package.
3. Require every observed `F=0` and `RAM_GAP>=4096`. Investigate any AGNSS
   ACK-NAK or OTA failure. Read back or otherwise establish the installed
   Bootloader identity against the reviewed V3.078 package where practical.
4. Attach logs and package/platform hashes to this candidate before generating
   or approving a formal production package.
