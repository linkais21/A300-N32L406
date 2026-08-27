# A300 to A300_406 Migration Design

## 1. Scope and fixed decisions

This design migrates the A300 standard baseline (`T360-A300_20260823000000,V1.274`) to A300_406 with the version string `T360-A300_406_20260823000000,V3.000`.

- Target MCU: N32L406CBL7, 64 MHz, 128 KB internal Flash, 24 KB SRAM.
- External Flash: BY25Q16ES, 16 Mbit SPI NOR.
- Schematic and connector architecture remain unchanged.
- OTA remote upgrade is mandatory and must be recoverable after power loss, network loss, bad images, and watchdog/fault resets.
- The application is statically allocated; no dynamic allocation or unbounded waits are allowed.

The target part name is CBL7. Existing C/D package and board records must be checked against the actual fitted part during hardware bring-up; a build for a different density/package is not accepted as evidence for CBL7.

## 2. Functional baseline and trimming

Retain the JT808 primary communication path, EC800M-CN control, GPS positioning, ACC/power monitoring, relay control, basic alarms, configuration persistence, mileage, blind-zone storage/replay, low-power operation, OTA, and recovery diagnostics.

Retain reduced features:

- F09: basic version, IMEI, identity, and health query.
- F19: basic parameter read/write.
- F39: only the approved SMS whitelist from `1_定位终端指令说明V1.0.xlsx`; two-entry bounded queue, maximum 192 bytes per command.
- F41: basic runtime diagnostics.
- F42: peripheral health checks and bounded recovery.
- F44: preserve the existing low-power business behavior; implement STOP2 on L406, with SLEEP fallback if STOP2 hardware validation fails.

Remove C21/BK A-GNSS, RTK/NTRIP, LBS, TTS, polygon geofences, vibration/illegal-movement alarms, detailed debug/statistics, Baler and CMCC custom functions, and unrelated GNSS model support. F16, F18, F23, F24, F31, and F33 are removed as previously approved. F26 supports only TAU804M and ATGM332D-F7N.

## 3. AGNSS architecture

Only two AGNSS implementations are shipped:

1. **TAU804M / Huada**: use the supplied Huada reference implementation and ALLYSTAR `F1 D9` time, location, and ephemeris messages.
2. **ATGM332D-F7N / Zhongkewei**: implement the supplied Zhongkewei AGNSS request/response flow, including authorized request parameters, response-header parsing, binary payload validation, and UART injection.

The code is separated behind a common manager:

```text
agnss_manager
  +-- agnss_huada.c       (TAU804M, F1 D9)
  +-- agnss_zhongkewei.c  (ATGM332D-F7N, Zhongkewei protocol)
  +-- agnss_storage.c     (BY25Q16ES dual-slot cache)
```

The selected receiver type is an explicit build/product configuration, not a permissive fallback from failed auto-detection. An unknown type runs ordinary GNSS only and never injects data using the wrong protocol.

The Huada reference requires two platform callbacks: millisecond delay and binary-safe UART write. The existing `gps_send_raw()` is the UART adapter. For Zhongkewei, credentials are provisioning data, not source-code constants. Missing/invalid authorization causes a bounded AGNSS failure and does not reset the device.

AGNSS uses a 512-byte to 1 KB shared transfer buffer. Data is streamed from EC800M to external Flash and later read in chunks to UART4. The old 8 KB resident ephemeris buffer is removed. OTA has priority over AGNSS; a shared EC800M/Flash arbiter prevents concurrent transfers.

## 4. External Flash layout

The BY25Q16ES address map is fixed and must be defined in one header used by bootloader and application:

| Region | Address | Size | Purpose |
|---|---:|---:|---|
| OTA Candidate | `0x010000` | 448 KB | Downloaded image and package metadata |
| Factory image | `0x080000` | 256 KB | Golden recovery image |
| LKG image | `0x0C0000` | 256 KB | Last known-good image |
| OTA Resume/BCR | `0x100000` | 64 KB | A/B boot records and Range checkpoint |
| Blind-zone metadata/data | `0x110000` | 644 KB | Existing 64-byte records, up to 10,000 entries |
| AGNSS metadata + slot A/B | `0x1B1000` onward | Reserved | Two independently committed AGNSS datasets |

AGNSS slots never overlap OTA, BCR, configuration, or blind-zone regions. Each slot has type, length, timestamp/sequence, CRC32, SHA-256, and a commit marker. Write data first, read it back, then commit metadata last. On boot, select the newest fully valid slot.

## 5. Internal Flash and bootloader

Internal Flash is divided as follows:

- Bootloader: `0x08000000-0x08002FFF` (12 KB reserved; release binary target <=11 KB).
- Application: `0x08003000-0x0801FFFF` (116 KB maximum; release target <=110 KB).

The bootloader is not upgraded through ordinary application OTA. It performs only bounded SPI access, package/product/hardware/address/length checks, SHA-256 and mandatory ECDSA signature verification, anti-rollback counter validation, internal Flash erase/program/readback verification, watchdog servicing, and recovery state transitions.

The boot control record (BCR) is redundant A/B with sequence and CRC. Installation is transactional:

```text
download Candidate -> verify complete package -> copy current App to LKG and verify
-> program App page-by-page with readback -> mark Trial -> boot
-> require N consecutive healthy boots -> commit Active
```

Candidate is never installed before its complete verification. A power loss during install causes a restart of the transaction; three failed Trial boots (including HardFault or watchdog reset) trigger LKG rollback. If LKG is invalid, Factory is attempted. If all images fail, the bootloader enters a controlled recovery state with bounded retries and watchdog protection instead of an endless reset loop.

## 6. MCU and peripheral adaptation

The N32L406 SDK is used for RCC, GPIO, UART4/UART5/USART1, SPI1, DMA, I2C1, ADC, RTC, EXTI, PWR, and IWDG. Pin mappings remain those in the board record. UART5 RX DMA remap, UART alternate functions (UART5 TX AF6/RX AF7; UART4 PB0/PB1 AF6), SPI timing, and APB clock calculations must be verified against the CBL7 SDK headers and measured on hardware.

Clock recovery after STOP2 must restore 64 MHz PLL, peripheral clocks, UART baud divisors, DMA, SPI, ADC, I2C, and SysTick before normal tasks resume. RTC, ACC, and required external interrupts are wake sources. Every wait has a timeout; a failed low-power transition falls back to SLEEP.

## 7. Runtime safety rules

- One owner for EC800M DMA RX and one arbiter for EC800M socket operations.
- One serialized owner for BY25Q16ES transactions; no OTA/AGNSS/blind-zone/config write overlap.
- No recursive AT transactions and no blocking operation without a deadline.
- Watchdog is fed only after the main scheduler and critical task-progress checks pass.
- HardFault/reset reason, stack watermark, Flash error, OTA state, and peripheral recovery counters are retained in a bounded diagnostic record.
- Logging is lossy/bounded and cannot block protocol, OTA, or watchdog service.

## 8. Versioning and build gates

All firmware, bootloader, manifest, JT808 version response, logs, and packaging metadata use exactly `T360-A300_406_20260823000000,V3.000`. The build must fail if an old A300/T663B version string remains in release-controlled files.

Acceptance gates:

1. Clean build for N32L406CBL7: zero errors and zero warnings; map confirms App <=110 KB and SRAM within 24 KB with margin.
2. Unit tests for both AGNSS parsers, frame boundaries, checksums, malformed data, time/location conversion, and slot commit/recovery.
3. OTA tests for Range resume, authentication/signature rejection, downgrade rejection, power loss at every install phase, three failed Trial boots, LKG/Factory fallback, and controlled recovery.
4. Hardware tests for UART/SPI/DMA, BY25Q16ES erase/program/readback, blind-zone replay, GNSS TTFF, AGNSS injection, STOP2 wake, and 72-hour watchdog/stability operation.

No release image is approved until all four gates pass on the fitted CBL7 hardware.
