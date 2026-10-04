A300-406 V3.081 EC800M startup probe HIL test image
Built: 2026-10-02 16:55:25 Asia/Shanghai
MCU: N32L406CBL7
Purpose: dedicated-device startup and SIM/network diagnostics only

FLASHING
1. Program only App-N32L406CBL7-V3.081-EC800M-POWER-PROBE-HIL.hex with a programmer that honors Intel HEX absolute addresses; or program App-N32L406CBL7-V3.081-EC800M-POWER-PROBE-HIL.bin at 0x08006000.
2. Program one file only. This package contains no bootloader or combined image.
3. Back up the device first. Do not upload this image as OTA or deploy it to production/fleet devices.

HIL CHECKS
1. Cold power-cycle the device and capture the complete debug UART log.
2. Check for [4G] power probe no OK rx=N echo=0/1; if present, report the values and confirm whether PWRKEY startup follows.
3. If startup advances, capture SIM detection, IMEI/ICCID query, registration, PDP and server connection results.
4. Include flashed file SHA-256 and timestamps with the returned log.

VALIDATION
Focused EC800M host regressions and firmware compilation passed. Release identity, RAM, trust-anchor and flash checks passed; Flash has low-headroom/configuration-change alerts.
Whole-program stack/heap/exception proof remains incomplete. This image is HIL only and hardware behavior is not verified.
