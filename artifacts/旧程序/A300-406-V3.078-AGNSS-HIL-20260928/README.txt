A300-406 V3.078 AGNSS hardware-validation package.
For an existing V3.077 device, use the OTA test flow first.
App-V3078.hex starts at 0x08006000; direct SWD App replacement bypasses OTA rollback.
SWD-Combined-V3078.hex contains Bootloader and App with absolute addresses.
SWD-Combined-V3078.bin starts at 0x08000000.
CAUTION: reflashing the Combined image reinstates the Bootloader factory-init request.
On first boot it erases external NOR configuration, BCR, checkpoint and authorization sectors.
Use Combined only on a blank board or an intentional factory recovery.
Upload OTA-A300-406-V3078.bin to the FOTA test platform as A300-406, version 3078; the platform must sign and authorize it.
HIL ONLY: the release RAM gate remains incomplete. Do not distribute as a formal release.
