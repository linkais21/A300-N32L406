V3.082 EC800M startup probe fix, dedicated-device HIL package only.
This package is not release approved because the repository release gate is blocked by
incomplete whole-program stack evidence and the existing hw_init.c IRQ-policy RAM guard.
Use Combined-N32L406CBL7.bin at 0x08000000 for a full SWD/production-tool image, or
App-N32L406CBL7.bin at 0x08006000 only when the existing bootloader is retained.
Do not use the previous V3.082 Trajectory-Fix package or the V3.081 DMA retest packages.
Validate cold boot, SIM/IMEI/ICCID, REG=1, PDP, JT808 online, and repeated HEALTH logs.
No physical device has been flashed or validated by this build step.
