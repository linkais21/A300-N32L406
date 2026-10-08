V3.082 trajectory fix dedicated-device HIL package.
Direct SWD test image: Combined-N32L406CBL7-V3.082.bin.
OTA upload image: OTA-A300-406-V3082.bin, model A300-406, version code 3082.
Upload only to the test FOTA platform with platform detached signing.
Acceptance: after OTA reboot, capture BOOT trial, 4G registration, JT808 online,
HEALTH F=0 and network heartbeat; the App must confirm trial ACTIVE after online.
Do not use for fleet deployment: release-gate.json records incomplete RAM/stack evidence.
