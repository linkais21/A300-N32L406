# A300-T9 GPS Tracker Firmware

Firmware for A300-T9 GPS vehicle tracker based on N32L406CDL7 MCU.

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
- I2C2 AF6, EC800M network registration/PDP, both TCP sessions and first-fix
  positioning require real-device/HIL verification before release.

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
- Make (or manually compile with provided scripts)

### Compile

```bash
make all
```

Output files in `build/`:
- `a300_firmware.hex` - Intel HEX format (for flashing)
- `a300_firmware.bin` - Binary format
- `a300_firmware.elf` - ELF format (for debugging)

### Flash Size

```
FLASH: 86,028 / 393,216 bytes (21.88%)
RAM:   12,588 / 32,768 bytes  (38.42%)
```

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
