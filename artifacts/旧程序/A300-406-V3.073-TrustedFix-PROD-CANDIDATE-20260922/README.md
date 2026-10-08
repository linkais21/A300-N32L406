# A300-406 V3.073 TrustedFix production candidate

- Combined-N32L406CBL7.bin: full SWD image at 0x08000000.
- App-N32L406CBL7.bin: App-only image at 0x08006000.
- A300-406-OTA-V3073.bin: OTA image, device model A300-406, version 3073.
- SHA256SUMS.json: hashes.

The supplied 2026-09-22 18:00 log does not contain a restored-fix line and shows GNSS no-fix throughout, so it is not proof of this behavior. Validate with a prior confirmed fix, reboot, then no-fix; expect `[GPS] restored trusted fix ...` and nonzero coordinates in 0x0200.

Build succeeded. release-guard and whole-program RAM/stack release gates are not passed; this is a production candidate pending those gates and HIL validation.
