A300-406 V3.080 AGNSS ACK hardware validation, built 2026-09-30 14:04:55 CST.
Firmware identity: T360-A300_406_20260930140455,V3.080; version counter 3080.

App-N32L406-V3.080-AGNSS-ACK.hex is an Intel HEX App image with absolute
addresses beginning at 0x08006000. The BIN is the same App image without
addresses; program it at 0x08006000 only. This package does not include a
Bootloader or Combined image. Direct App SWD programming bypasses OTA trial
and rollback; use a dedicated validation device.

This is HIL TEST ONLY, not a production release. Flash remaining: 596 bytes.
The release guard and Flash capacity guard pass, but the RAM/whole-program
stack gate is incomplete (first unresolved root: ADC_IRQHandler). Firmware
version counter remains 3080, so this package is not a same-version OTA update.

Capture the exact flashed identity and complete debug/UART4 traces. Verify:
1. Cold-start command F1 D9 06 40 01 00 01 48 22 precedes each injection.
2. Only HD_BDS.hdb/BDS 0x33 frames are injected; each frame receives the
   matching ACK before the next frame. Include NAK and timeout recovery.
3. AID-TIME and AID-POS are optional and precede ephemeris when present.
4. Compare AID-TIME with a reliable UTC reference (guide limit +/-3 s),
   check time never moves backward, and measure position error (<75 km).
5. Check first-fix time, repeat injections, offline recovery and normal GPS
   reporting. Keep the captured firmware hash with the results.
