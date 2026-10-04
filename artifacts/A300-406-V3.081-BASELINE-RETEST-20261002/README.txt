A300-406 V3.081 baseline network retest image
MCU: N32L406CBL7
Purpose: dedicated-device network registration test

FLASHING
1. Recommended: program App-N32L406CBL7.hex with a tool that honors Intel
   HEX addresses. It targets the App at 0x08006000.
2. Alternatively, program App-N32L406CBL7.bin at address 0x08006000.
3. Program only one of these App files. Do not program both, and do not use
   this App image as an OTA package.
4. This package contains no Bootloader or Combined image. It replaces only
   the App and is intended to preserve the device's existing configuration.

IMAGE IDENTITY
These files are byte-for-byte copies of artifacts/V3.081. They were not
rebuilt from the current workspace source. The original V3.081 manifest marks
its source worktree dirty, so this package identifies the known baseline
binary by its recorded hashes rather than claiming a reproducible source
build.

Before testing, record the flashed file hash and capture the complete debug
UART and modem UART logs from a cold start. Check SIM detection, IMEI/ICCID,
network registration, PDP activation, and application server connection.
Repeat after a cold power cycle. Network registration remains to be verified
on the device; creating this package does not establish HIL success.
