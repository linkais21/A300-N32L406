# N32L406CBL7 DEV-KEY development build report

Build time: 2026-08-29 13:54 CST  
Target: N32L406CBL7, 64 MHz, 128 KiB Flash, 24 KiB SRAM  
Key label: `DEV-KEY`  
Version counter: `20260829`

## Result

**N32L406CBL7 DEV-KEY development build complete; not production-ready.**

The final output directory is:

`dist/dev-key/20260829T055417Z/`

The independently validated artifact manifest is:

`dist/dev-key/20260829T055417Z/SHA256SUMS-N32L406CBL7-DEV-KEY.json`

The directory contains Bootloader ELF/HEX/BIN/map, App ELF/HEX/BIN/map, a
signed App package, and a combined programming BIN. Every artifact filename
contains `N32L406CBL7-DEV-KEY`.

## Frozen layout and final size

- Bootloader: `0x08000000..0x08005FFF`, 24 KiB maximum.
- App: `0x08006000..0x0801FFFF`, 104 KiB maximum.
- Final Bootloader BIN: 10,428 bytes.
- Final App BIN: 78,972 bytes.
- Final App static RAM guard: 19,724 / 20,480 bytes.
- App vectors validated: MSP `0x20006000`, reset handler `0x0801205D`.

## Automated verification

- All sorted `tools/tests/test_*.py` were run with `REQUIRE_GCC=1`; the run
  covered real host-C P-256 verification vectors and completed through
  `test_zhongkewei_agnss.py`.
- `python tools/release_guard.py`: PASS.
- `python tools/tests/test_feature_guards.py`: PASS.
- App and Bootloader were force-rebuilt with ARM GNU Toolchain 14.3.1; build
  output contained no warnings.
- App and Bootloader map guards: PASS.
- Both final ELFs contain `firmware_signature_verify` and `uECC_verify` and do
  not contain `uECC_sign`, `uECC_make_key`, or `uECC_shared_secret`.
- Signed package was verified offline against the public key embedded in the
  firmware. The private key matches that public key and remains only in the
  ignored `.keys/` directory.
- `python tools/tests/test_dev_release_manifest.py --manifest ...`: PASS;
  artifact sizes and SHA-256 hashes were independently recomputed.
- `git diff --check`: exit 0; only Windows line-ending conversion notices.

## Implemented migration closure

- Closed both confirmed blind-zone no-progress state-machine loops.
- Frozen N32L406CBL7 memory limits and early App VTOR relocation.
- Added one canonical signed-package digest and ECDSA P-256 DEV-KEY flow.
- Added the pinned upstream micro-ecc verifier shared by App and Bootloader.
- Added real N32L406 Bootloader SPI NOR, internal Flash, watchdog, reset and
  safe vector-jump platform code.
- Removed Bootloader signing. LKG stores and re-verifies complete signed
  packages and is promoted only after the App marks a Trial healthy.
- Unified App/Bootloader BCR wire format, rollback floor and wrap-safe sequence
  selection; App Pending/Trial/Active transitions use erase/write/read-back.
- Added STOP2 entry with both SRAM banks retained, bounded preconditions,
  shallow-sleep fallback, ordered hardware restoration and reset diagnostics.

## External gates not executed

The following remain mandatory before production release:

- Bootloader vector jump on N32L406CBL7 hardware.
- Candidate install with power cuts at each erase/write/BCR/LKG transition.
- Trial, LKG and Factory rollback on real SPI NOR and internal Flash.
- Watchdog, brownout and reset-flag classification tests.
- RTC, ACC, charge and other EXTI wake tests from STOP2.
- 64 MHz clock/peripheral recovery and post-wake modem/GNSS recovery.
- STOP2 current measurement and long-duration wake cycling.
- Zhongkewei vendor or capture validation; current path remains fail-closed.
- 72-hour mixed-load soak test.

No firmware was flashed, no device command was sent, and no commit, push or
deployment was performed.
