# V3.083 / 3083 release candidate

Status: dedicated-device validation only. Do not publish to the production fleet yet.

## Test the OTA path first

1. Keep the test device on its current V3.082 App and compatible Bootloader. Record its current version and online state.
2. Check whether the platform already has an `A300-406` / `3083` entry. If so, compare its package SHA256 with `SHA256SUMS-N32L406CBL7.json` before doing anything else. Otherwise, upload `A300-406-OTA-V3083.bin` with device model `A300-406`, version code `3083`, and version name `V3.083`. Keep "mandatory" off. The platform validates the header and signs the image; this file is not a directly flashable App image.
3. Enable this firmware, then import only the dedicated test device into its upgrade list without the force option. The platform requires an enabled image for assignment, and a device without an assigned task does not receive it merely because the image is enabled.
4. Capture serial logs and platform task history from update check through download, install, trial boot, success acknowledgement, and return to JT808 online. Confirm the next update check does not offer 3083 again.
5. Test offline storage and replay. Compare source and platform record counts, confirm no duplicate or missing records, and use timestamped logs to check at least 1000 ms between acknowledged `0x0704` batches.
6. Observe the exact installed candidate for resets, watchdog/HardFault, EC800M registration, JT808 heartbeat, and RAM/Flash errors over the agreed acceptance window. Preserve the logs and SHA256 manifest.

## SWD check on a separate device

Flash `App-N32L406CBL7.hex` to a device with the compatible Bootloader. Its Intel HEX addresses start at `0x08006000`. When flashing `App-N32L406CBL7.bin`, explicitly set address `0x08006000`.

Do not use `Combined-N32L406CBL7.bin` on an existing device containing user data. It includes a Bootloader factory-init request that may erase external Flash sectors. Reserve it for a separately approved blank-device provisioning procedure.

The candidate is releasable only after the test results, Flash headroom warning acceptance, and final package hashes are recorded. `SHA256SUMS-N32L406CBL7.json` identifies these exact binaries.
