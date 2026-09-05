# A300-T9 Hardware Pin Bring-Up Design

## Scope and authority

This design aligns the N32L406 firmware with the hardware mapping confirmed by the user on 2026-08-29. That confirmation overrides the stale pin table in `README.md` and the current pin definitions in `include/config.h`.

The change covers the MCU pin contract, EC800M UART/control pins, GPS UART and enable pin, USART1 diagnostic output, vehicle ACC and voltage sensing, and the DA218E I2C/interrupt interface. It does not change the PCB, bootloader protocol, JT808 wire format, deployment environment, or generated firmware artifacts.

## Frozen hardware mapping

| Function | MCU resource | Electrical/firmware role |
|---|---|---|
| Hardware ACC (`M_ACC_IN`) | PA12 | Q9-inverted input; external ACC ON drives PA12 low; EXTI12 wake source |
| Vehicle voltage (`CAR_ADC`) | PA3 / ADC_IN4 | Analog input using the existing 180 kOhm / 5.6 kOhm divider and 33.2 ratio |
| Battery voltage (`BAT_ADC`) | PA1 / ADC_IN2 | Unchanged analog input |
| DA218E SDA | PD14 / I2C2_SDA | Open-drain alternate function with board pull-up |
| DA218E SCL | PD15 / I2C2_SCL | Open-drain alternate function with board pull-up |
| DA218E INT1 | PB3 | Digital interrupt input; diagnostic/interrupt plumbing only until the exact DA218E interrupt mode is configured |
| Light sensor interrupt (`GUANG_INT`) | PA0 | Digital EXTI0 input; moved off PB0 so it cannot conflict with UART4 TX |
| GPS TX/RX | PB0/PB1 / UART4 | MCU TX to module RX; MCU RX from module TX; 115200 baud |
| GPS enable | PB6 | Independent active-high GPIO output; never switched to I2C alternate function |
| EC800M TX/RX | PB4/PB5 / UART5 | MCU TX to MAIN_RXD; MCU RX from MAIN_TXD; 115200 baud |
| EC800M DTR | PB7 | Independent GPIO output |
| EC800M PWRKEY | PA8 | Active-low pulse, existing EC800M timing retained |
| EC800M power enable | PA15 | Active-high output |
| Diagnostic TX/RX | PA9/PA10 / USART1 | 115200 baud console |

PD14 and PD15 are also OSC_IN/OSC_OUT. The firmware must continue to build with `SYSCLK_SRC=3` and `SYSCLK_FREQ=64000000`, using the internal HSI PLL. Enabling HSE would conflict with I2C2 and is outside this design.

## Firmware architecture

### Central pin contract

`include/config.h` remains the single firmware pin map. The ACC, vehicle ADC, I2C peripheral/clock/pins, and DA218E INT1 definitions will be corrected there. DA218E address probing already present in the worktree is retained because the supplied hardware evidence does not settle the `0x26/0x27` documentation conflict.

### GPIO, ADC, and I2C initialization

`src/hw_init.c` will:

- configure PA12 as the ACC digital input;
- configure PA3 as an analog ADC input and select ADC channel 4;
- initialize I2C2 on PD14/PD15 with the N32L406 alternate function documented for those pins;
- configure PB3 as the DA218E INT1 input;
- configure PA0 as the light-sensor input and route EXTI0 to GPIOA;
- leave PB6 permanently under GPS enable GPIO ownership;
- leave PB7 permanently under EC800M DTR GPIO ownership.

The STOP2 restore path will call the same initialization functions so the ownership and alternate-function mapping are restored consistently after wake.

### ACC wake handling

`src/power_mgr.c` will move ACC from EXTI3 to EXTI12. EXTI12 and the existing PB15 charge input share `EXTI15_10_IRQn`, so one handler will inspect and clear each pending line independently. STOP2 preparation will clear EXTI12 instead of EXTI3. Polling and JT808 status generation treat a low PA12 level as external ACC ON because Q9 inverts the signal.

No ADC interrupt is assigned to PA3. Vehicle power remains sampled by `adc_monitor_process()` once per second.

### GPS enable ownership

`src/gps.c` will reduce `gps_enable()` to bounded GPIO high/low control. It will not switch PB6 into I2C1 mode. This removes the current hidden dependency between GPS power and the accelerometer bus.

### DA218E behavior and INT1

The existing bounded DA218E register transactions and startup address diagnostics will be migrated from I2C1 to I2C2 through the central `BSP_I2C` definitions. The existing polling-based motion algorithm remains the behavior source for this change.

PB3 INT1 will be initialized and exposed in the pin contract. This change will not invent DA218E motion-interrupt register values or polarity. Interrupt-driven motion wake will be enabled only when confirmed by the DA218E datasheet or HIL evidence; until then, PB3 is available for level diagnostics and future EXTI wiring without changing current motion semantics.

### Diagnostic evidence

The USART1 console will report a concise hardware-contract banner at startup containing the selected ACC pin, vehicle ADC channel, I2C peripheral/pins, and the sampled DA218E INT1 level. Existing DA218E probe-stage logs and EC800M state logs are retained. Logging remains outside ISRs and contains no IMEI, key, server credential, or location data.

## Error handling and safety

- I2C transactions retain bounded timeouts and bounded address retries.
- A missing DA218E logs the failed stage and allows the main loop to continue.
- ACC and charge pending bits are handled independently in the shared ISR.
- UART, I2C, and ADC initialization contain no unbounded waits.
- No flash format, OTA state, relay authorization, or production deployment behavior changes.
- No firmware is flashed and no real device command is sent as part of host-side verification.

## Verification design

Contract tests will first fail against the old mapping, then pass after implementation. They will assert:

1. ACC uses PA12 and `EXTI_LINE12`/`GPIO_PIN_SOURCE12`/`EXTI15_10_IRQn`.
2. Vehicle ADC uses PA3 and `ADC_CH_4`.
3. DA218E uses I2C2 on PD14/PD15 with the correct alternate function.
4. PB6 is not switched to an I2C alternate function by `gps_enable()`.
5. PB7 remains EC800M DTR and PB3 is defined as DA218E INT1.
6. The shared EXTI handler services both line 12 and line 15.
7. UART4, UART5, and USART1 mappings remain unchanged.

After targeted tests, verification will include the relevant host test suite, `make all`, `make release-guard`, `make ram-guard`, and `git diff --check`. Existing failures unrelated to this task will be reported rather than hidden.

The following remain mandatory HIL checks because compilation and source-contract tests cannot prove electrical operation:

- measure PA12 transitions with ACC off/on (high when off, low when on) and confirm wake from STOP2;
- inject known vehicle voltages and validate PA3 ADC readings and divider calibration;
- capture PD14/PD15 waveforms, DA218E ACK/address/ID, and XYZ samples;
- observe PB3 INT1 level during motion before enabling interrupt-driven semantics;
- verify UART4 NMEA reception, PB6 GPS power control, UART5 EC800M AT exchange, PB7 sleep control, and PA9 diagnostic output.
