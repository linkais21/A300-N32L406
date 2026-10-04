A300-406 V3.082 EC800M UART5 RX DMA remap HIL image

MCU: N32L406CBL7
Version: T360-A300_406_20261003135453,V3.082
Scope: dedicated test device with its existing Bootloader retained.

SWD programming:
1. Back up the device and record the flashed file SHA-256.
2. Program the HEX file, which has absolute App addresses starting at
   0x08006000. Alternatively, program the BIN at address 0x08006000.
   Program one file only. This package contains no Bootloader or Combined
   image; do not program the BIN at 0x08000000.
3. Power-cycle the device and capture the complete debug UART log.

HIL checks:
- Read DMA5.CHSEL at 0x40020068 through SWD after App initialization;
  UART5_RX must select 0x0A. DMA5.TXNUM at 0x4002005C should change
  when modem bytes arrive.
- Confirm [4G-IO] probe/init diagnostics, SIM and identity queries,
  registration, PDP activation, and JT808 online state.
- Repeat after a cold power cycle and record the log and file SHA-256.

This image is for HIL only. The App build, vectors, host tests, Flash guard,
and release guard passed. RAM guard remains blocked by changed IRQ-policy
source evidence in hw_init.c; whole-program stack proof is incomplete.
No device was flashed or validated by the packaging step.
