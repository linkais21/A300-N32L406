A300-406 V3.081 EC800M UART-DMA HIL test image
Built: 2026-10-02 (Asia/Shanghai)
MCU: N32L406CBL7
Purpose: dedicated-device SIM/network connectivity test only

FLASHING
1. Use App-N32L406CBL7-V3.081-EC800M-DMA-HIL.hex with a programmer that
   honors Intel HEX addresses; or use the BIN at address 0x08006000. The HEX
   includes explicit zero-fill records and reconstructs the BIN exactly.
2. Program only one of those files. Do not program a Bootloader or Combined
   image from this package; neither is included.
3. Back up the device first and use one dedicated test device. Do not upload
   this image as an OTA or use it for fleet/production deployment.

HIL CHECKS
1. Capture the complete debug UART and modem UART traces from cold start.
2. Confirm the SIM is detected and IMEI/ICCID queries complete.
3. Confirm modem registration, packet service/PDP activation, and the normal
   application server connection. Repeat after a cold power cycle.
4. Record the flashed file SHA-256, device identity, SIM result, registration
   state, and any network connection failure with timestamps.

IMAGE IDENTITY
The network/JT808 version string is
T360-A300_406_20261002162151,V3.081 (counter 3081).
The startup/log build stamp currently embeds
T360-A300_406_20261001234347,V3.081 (counter 3081). This timestamp mismatch
is present in the workspace headers and is recorded here so the test result
can be tied to the exact binary.

VALIDATION STATUS
The focused UART-DMA regression test and firmware compilation pass. The
release guard does not pass: it reports a noncanonical FW_FULL_VERSION use
in src/main.c and a FW_FULL_VERSION timestamp mismatch in
include/build_version.h. Flash usage is 104604/106496 bytes (1892 bytes
remaining), with LOW_HEADROOM and CONFIGURATION_CHANGED alerts. The RAM guard
passes with a 4128-byte runtime gap against a 4096-byte requirement; the
whole-program stack/heap proof remains incomplete. This package is not release
approved, and hardware/HIL behavior has not been verified.
