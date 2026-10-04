A300-406 V3.081 EC800M UART5 DMA retest image - REJECTED
MCU: N32L406CBL7
Firmware version: T360-A300_406_20261002171910,V3.081
Status: HIL failed; do not flash this image again

FLASHING
1. Program either the BIN at 0x08006000 or the Intel HEX file with a
   programmer that honors its absolute addresses. Program only one file.
2. This package contains the application image only. It does not contain a
   Bootloader, Combined image, or OTA package.
3. Use one dedicated test device and retain its existing backup. This is not
   approved for fleet or production use.

HIL RESULT
Cold-start log reported "power probe no OK rx=0 echo=0". The modem did not
respond to AT, so this image did not restore SIM detection or registration.
Use the known V3.081 baseline image in artifacts/V3.081 for rollback testing.

VALIDATION
Build and release guard passed. RAM guard passed with a 4128-byte runtime gap
against a 4096-byte requirement. Flash use is 104716/106496 bytes (1780 bytes
remaining); LOW_HEADROOM and CONFIGURATION_CHANGED alerts remain. Whole-program
stack/heap/exception proof is incomplete. HIL was run and failed because the
modem returned no bytes to the AT probe. Do not use this package for retesting.

After flashing, return the complete cold-start debug UART log, modem UART
trace if available, the flashed file name and SHA-256, SIM detection result,
and registration/PDP/server connection results with timestamps.
