A300-406 V3.076 -> V3.077 stability HIL test pair

1. Program SWD-Combined-V3076.hex, or the matching BIN at 0x08000000.
   Verify first boot and the one-time external NOR factory initialization.
2. Upload OTA-A300-406-V3077.bin to the FOTA test platform as model
   A300-406, version code 3077. The platform must sign and authorize it.
3. Upgrade a V3.076 test device and verify trial, ACTIVE, LKG and
   token-bound SUCCESS. Do not upload a Combined image as an OTA body.
4. SWD-Recovery-Combined-V3077 is a recovery image, not the OTA test
   baseline. Its HEX carries addresses; its BIN starts at 0x08000000.

HIL TEST ONLY: release-gate fails on incomplete RAM/stack proof.
Real power-cut, weak-network and rollback tests are still required.
