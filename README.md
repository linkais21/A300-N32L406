# A300-T9 GPS Tracker Firmware

## V3.049 optimization closure test build (2026-09-15)

Current hardware validation delivery: `artifacts/HIL-STABILITY-20260915-V3049/`.
Read the [flashing, serial capture and 17-item closure guide](docs/quality-closure-v3049-20260915.md)
and fill in the [test record](docs/HIL-RESULTS-TEMPLATE.md).
Includes the current TAU804M-only AGNSS optimization inputs. `release_approved=false`:
the complete RAM/stack gate remains blocked; PERF-01 is only partially addressed.
Combined SWD first boot clears configuration and OTA authorization state.

## V3.048 stability test build (2026-09-15)

Recent optimization review and query workspace lifetime repair are packaged in
`artifacts/HIL-STABILITY-20260915-V3048/`. See
[review and validation](docs/stability-review-v3048-20260915.md).
This is a hardware test build, `release_approved=false`: whole-program RAM/stack
evidence remains incomplete. Combined SWD images request one-time factory initialization.
The version references below describe earlier releases.

Firmware for A300-T9 GPS vehicle tracker based on N32L406CBL7 MCU.

## Hardware

- **MCU**: N32L406CBL7 (ARM Cortex-M4, 128 KiB Flash, 24 KiB SRAM)
- **4G Module**: Quectel EC800M-CN (LTE Cat-1, with iFlytek TTS)
- **GPS Module**: TAU804M-N2B0 (BeiDou dual-frequency RTK)
- **Flash**: BY25Q16 (16Mbit SPI Flash)
- **Accelerometer**: DA218E (I2C)

## Features

- JT/T 808-2013 registration, authentication, heartbeat and positioning
- 4G LTE connectivity (EC800M)
- GPS/BeiDou positioning with RTK support
- FOTA (Firmware Over-The-Air) updates
- Geofencing
- Remote relay control (fuel cutoff)
- ADC monitoring (vehicle voltage, battery voltage)
- AT command configuration via debug UART

## JT/T 808-2013 Online Contract

- Release identity is defined by `release_identity.json`. This release is
  `T360-A300_406_20260823000000,V3.041`; subsequent firmware changes increment
  only the three-digit revision (`V3.038`, `V3.039`, ...). The OTA model is
  `A300-406`, while the JT808 terminal model and manufacturer are
  `T360-A300` and `70110`.
- A valid terminal PID is exactly 11 decimal digits. When PID is empty, the
  firmware derives it from the last 11 digits of an exact 15-digit IMEI and
  persists it before sending any JT808 frame.
- The 2013 message-header phone field is `0 + PID` (12 digits encoded as six
  BCD bytes); the `0x0100` terminal ID is the final seven PID digits.
- Primary CH0 and backup CH3 are independent sessions. Each connection has its
  own registration/authentication transaction, TCP generation, retries,
  backoff and persisted authentication code.
- New and factory-reset configurations keep CH3 disabled. Configure it with
  `FIP,<host>,<port>#` (for example `FIP,58.61.154.237,7018#`) and disable it
  with `FIP,0#`. Firmware upgrades preserve any non-empty FIP already stored
  by earlier versions, including legacy domain names.
- Once per boot, after identity validation and any required PID persistence,
  the debug UART prints full IMEI, ICCID, device ID, JT808 terminal ID, PID
  source, main endpoint and either the configured backup endpoint or
  `BACKUP=OFF`. Identity failures are rate-limited and include the failing
  stage (`IMEI_FORMAT`, `PID_FORMAT`, `FLASH_LOCK`, `FLASH_WRITE`, or `VERIFY`).
- After a channel authenticates, it receives `0x0200` immediately when a fresh
  valid GNSS position and date/time are available. Otherwise it waits for the
  first valid fix. Zero, stale and frozen coordinates are never reported as a
  valid real-time fix.
- A live valid `0x0200` sets both status bit1 and BeiDou status bit19. A
  retained sleep position clears bit1 but preserves bit19 to identify the
  trusted position source as BeiDou.
- After first authentication on each boot, CH0 and configured CH3 independently
  upload one `0x0107` terminal-attributes packet. Delivery completes from the
  modem send result and does not wait for a platform acknowledgement. Later
  `0x8107` queries still receive an immediate `0x0107` response on the
  requesting channel.
- I2C2 AF6, EC800M network registration/PDP, both TCP sessions and first-fix
  positioning require real-device/HIL verification before release.

## Stationary Soak Follow-up

See [EC800M DMA wrap repair and shared App SHA-256](docs/stability-rx-sha-20260913.md)
for the staged engineering comparison: RX repair followed by SHA consolidation
reduces App usage to 105,160 B (1,336 B free). This is not a new versioned release;
RAM/release gates still fail and the field watchdog resets require another HIL soak.

## Versioned Release Artifacts

Delivery policy confirmed on 2026-09-14: each future delivery advances one version
and provides both a Combined SWD image and an OTA package containing the same
version of the App. Create two sequential versions only when explicitly requested.
The latest request makes V3.046 and V3.047 an explicit exception for validating
new Bootloader installation progress: SWD V3.046, then OTA V3.047.
Formal release labeling still requires the release gates and hardware acceptance;
an incomplete RAM/stack gate must remain visible. See
[OTA log and progress update](docs/ota-progress-20260914.md).

The current stability test pair is [SWD V3.040 → OTA V3.041](artifacts/HIL-STABILITY-20260913-V3040-V3041/README.md): RX boundary repair first, then shared SHA. Both retain failed RAM/release status and require HIL.

The current optimization HIL pair is
[`HIL-OPT-20260913-V3038-V3039`](artifacts/HIL-OPT-20260913-V3038-V3039/README.md):
SWD V3.038 followed by OTA V3.039. These are user-requested test images;
RAM/release gates remain failed and hardware acceptance is pending.

The paired validation delivery is
[`artifacts/OTA-TEST-V3036-V3037/README.md`](artifacts/OTA-TEST-V3036-V3037/README.md):
flash the V3.036 Combined image over SWD, then upload the V3.037 OTA image.

OTA trust-anchor repair and verification instructions are in
[`docs/ota-trust-repair-2026-09-12.md`](docs/ota-trust-repair-2026-09-12.md).
Run `python tools/tests/test_platform_trust_anchor.py` before releasing; it
compiles the shipped public key and validates a real platform signature, using
a host GCC or Clang compiler. The release builder runs this check automatically.
Devices with the former incorrect public key require a coordinated App and
Bootloader repair over SWD; a new OTA package cannot repair its own rejecting
verifier. Do not reuse an archived version number for a changed image.

Generate a release from the repository root with:

```powershell
python tools/build_dev_release.py
```

The builder reads the release version from `release_identity.json` and writes
all outputs to `artifacts/<version>/`. The current release is stored in
`artifacts/V3.037/` and contains:

- `Combined-N32L406CBL7.bin`: complete Bootloader and App programming image.
- `App-N32L406CBL7.bin`: App-only programming image.
- `Bootloader-N32L406CBL7.bin` and `.hex`: Bootloader programming images.
- `A300-406-OTA-V3037.bin`: firmware package uploaded to the FOTA platform.
- App and Bootloader `.elf`, `.hex`, and `.map` diagnostic artifacts.
- `SHA256SUMS-N32L406CBL7.json`: artifact sizes and SHA-256 hashes.

Version directories are immutable. If `artifacts/V3.006/` already exists, the
builder fails before compiling and does not overwrite or merge any files. An
alternate root can be selected with `--output D:\some\root`; the current
release is then written to `D:\some\root\V3.006` with the same collision rule.

### Production Combined initialization

Every newly built production `Combined-N32L406CBL7.bin` carries a pending
one-time initialization request in the Bootloader page at `0x08005800`.
Production programming must erase and verify the complete internal Flash image;
on first boot the Bootloader then clears only configuration A/B, BCR A/B, OTA
checkpoint A/B, and OTA authorization A/B before starting the App. Candidate,
Factory, LKG, blind-zone, and AGNSS regions are preserved. Completion is written
only after all eight sectors read back erased, so a power interruption retries
safely on the next reset.

App-only SWD programming and OTA start at `0x08006000`, preserve the completed
request, and therefore preserve external configuration. A normal reset also
does not repeat initialization. An MCU internal mass erase does not erase the
external BY25Q16; use the production Combined flow to deliberately request the
selective cleanup.

Validate a production image without hardware access:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/flash_combined_and_selftest.ps1 `
  -CombinedPath artifacts/<version>/Combined-N32L406CBL7.bin -Port COM4 -DryRun
```

Remove `-DryRun` and provide `-ProgrammerPath` (or `PROG_CLI`) for an authorized
production operation. The wrapper performs internal erase, write/verify and
reset, then grades a bounded 115200 8N1 debug-UART capture without printing the
raw IMEI, ICCID, location, server address, or credentials. A valid GNSS fix is
reported separately and is not required for an indoor production pass.

## Pin Configuration

| Function | MCU Pin | Notes |
|----------|---------|-------|
| 4G TX | PB4 | UART5_TX (AF6) |
| 4G RX | PB5 | UART5_RX (AF7) |
| 4G PWRKEY | PA8 | Power key control |
| 4G DTR | PB7 | Sleep control |
| 4G Power Enable | PA15 | High = enable |
| GPS TX | PB0 | UART4_TX |
| GPS RX | PB1 | UART4_RX |
| GPS Enable | PB6 | LDO enable |
| GPS LED | PD0 | Blue LED |
| Vehicle ADC | PA3 | ADC_IN4 |
| Hardware ACC | PA12 (Q9 collector) | Low = external ACC ON, high = ACC OFF, EXTI12 wake |
| DA218E SDA | PD14 | I2C2_SDA; requires internal HSI clock |
| DA218E SCL | PD15 | I2C2_SCL; requires internal HSI clock |
| DA218E INT1 | PB3 | Digital input |
| SPI Flash CS | PA4 | Software CS |
| SPI Flash SCK | PA5 | SPI1_SCK |
| SPI Flash MISO | PA6 | SPI1_MISO |
| SPI Flash MOSI | PA7 | SPI1_MOSI |
| Debug TX | PA9 | USART1_TX (115200 baud) |
| Debug RX | PA10 | USART1_RX |

## Building

### Prerequisites

- ARM GCC toolchain (arm-none-eabi-gcc)
- GNU Make 4.3+ (grouped ELF/MAP/build-profile outputs; verified with 4.4.1)

### Compile

```bash
make all
```

Output files in `build/`:
- `a300_firmware.hex` - Intel HEX format (for flashing)
- `a300_firmware.bin` - Binary format
- `a300_firmware.elf` - ELF format (for debugging)

### Flash Size

The N32L406CBL7 has 128 KiB internal Flash and 24 KiB SRAM. The linker
script `ldscript/n32l406.ld` reserves 24 KiB for the Bootloader and assigns
104 KiB (106,496 bytes) to the App at `0x08006000`.
The 2026-09-13 full-build baseline uses **105,776 bytes (99.32%)**, leaving
**720 bytes**. Static RAM is 17,820 / 24,576 bytes; stack/runtime safety remains
a separate validation requirement. These are historical measurements, not
current-worktree optimization budgets; use freshly generated BIN/MAP and
capacity/stack reports for the build being evaluated.

`make all` and `make release-gate` run `flash-guard`, which compares the BIN
length with the MAP load span and writes `build/flash-capacity.json`. Remaining
space below 4,096 bytes emits `LOW_HEADROOM`; overflow or inconsistent/missing
evidence fails the build. The release builder archives the report and includes
its hash in the release manifest. Run `make -B all` for release/CI validation;
ordinary App incremental builds now track direct/transitive headers and effective
build options, including switching options back. Old objects without dependency
files rebuild automatically. See [BUILD-01 incremental dependencies](docs/build01-incremental-dependencies.md)
for coverage, commands and remaining limits.

See [RES-01 capacity gate](docs/res01-flash-capacity-gate.md) for baseline,
configuration drift, commands and validation limits.

### Final LTO Stack Evidence (RAM-01)

`make stack-report` generates ELF/MAP-bound final LTO stack diagnostics.
`make ram-guard`, `make stack-guard`, `make release-gate` and the release builder
reject incomplete runtime evidence. The historical RAM-01 baseline direct-call frame sum
is 2,984 bytes, leaving 3,772 bytes before heap/IRQ and other unmeasured usage,
below the required 4,096-byte gap. Release is blocked pending verified bounds;
`make all` success is only a build result. Force the first rebuild with `-B`.
See [RAM-01 evidence, tests and HIL requirements](docs/ram01-lto-stack-gate.md).

## Recent Changes

**2026-06-05**: Fixed hardware pin definitions
- Corrected EC800M 4G module UART (USART3 → UART5)
- Fixed SPI Flash pins (PB3/4/5 → PA5/6/7)
- Fixed GPS LED pin (PB14 → PD0)
- Added EC800M power enable control (PA15)
- **Result**: 4G communication now works correctly

See [FIRMWARE_CHANGES.md](FIRMWARE_CHANGES.md) for detailed change log.

## AT Commands

Connect to debug UART (PA9/PA10, 115200 baud):

```
VERSION       - Query firmware version
SERVER        - Set main server (IP,port)
HEARTBEAT     - Set heartbeat interval (1-10 min)
POSITION      - Query current GPS position
RELAY         - Control relay (ON/OFF)
REBOOT        - Remote reboot
FACTORY       - Factory reset
```

Full command list in [CLAUDE.md](../CLAUDE.md).

## License

Proprietary - For internal use only.

## Contact

- Repository: https://github.com/yiworkdev-dotcom/A300-first
