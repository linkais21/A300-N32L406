# A300-406 V3.079 RAM/HIL test build

Firmware identity: `T360-A300_406_20260928114155,V3.079` (version code 3079).
Hardware: N32L406CBL7. OTA model: `A300-406`.

| File | Use | Bytes | SHA-256 |
| --- | --- | ---: | --- |
| `App-N32L406-V3.079-TEST-ONLY.bin` | App image for inspection or isolated bench recovery | 105220 | `9e811e5cf62d2c2a168aec7ea204f42516910073245ed7abbeb9db9bb4d6c48d` |
| `A300-406-OTA-V3079-TEST-ONLY.bin` | Upload to the existing FOTA platform for one dedicated test unit | 105252 | `58af14f70ded1f2e4084a222fbc9c6544ba47df2c2f9ee409712cf51c7a42768` |

The OTA file is the 32-byte A300 transport header followed by the App image.
Its header has version 3079, product ID `0x41333030`, body length 105220,
and body CRC32 `0x835d131c`. The existing FOTA platform supplies the detached
signature during its upload flow; this file contains no private signing key.

This is a test build, not a production release. The final-link Flash check,
version contract, OTA format check, and necessary RAM budget pass. The full
release gate still fails because the whole-program stack, indirect calls,
interrupt nesting, and fault frames do not have a proven upper bound. Do not
use a fleet-wide campaign or upgrade production units with this image.

On the dedicated unit, record the complete serial trace for a normal OTA,
power interruption/recovery, network interruption/recovery, AGNSS injection,
and several post-upgrade HEALTH reports. Confirm the boot banner and FOTA
version are V3.079. Keep the V3.078 production image available for recovery.
