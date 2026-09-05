# A300-T9 Hardware Pin Bring-Up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align the N32L406 firmware with the confirmed A300-T9 ACC, vehicle ADC, DA218E, GPS, EC800M, and diagnostic UART wiring.

**Architecture:** Keep all board resources centralized in `include/config.h`, then make peripheral initialization and wake logic consume that contract. Add source-contract tests before each behavior change, preserve the existing bounded DA218E polling driver, and separate GPS_EN/DTR GPIO ownership from the new I2C2 bus.

**Tech Stack:** C99, N32L40x standard peripheral library, ARM GNU Make build, Python contract tests.

## Global Constraints

- Target MCU is N32L406CBL7, 128 KiB Flash and 24 KiB SRAM.
- Keep `SYSCLK_SRC=3` and `SYSCLK_FREQ=64000000`; PD14/PD15 cannot be used with HSE.
- Preserve all unrelated and pre-existing worktree changes.
- Do not commit, push, flash hardware, deploy, or send a real device control command.
- Do not enable DA218E INT1 motion semantics without confirmed register/polarity evidence.
- All ISR work remains limited to checking/clearing flags and posting wake events.

---

### Task 1: Freeze and test the board resource contract

**Files:**
- Create: `tools/tests/test_hardware_pin_contract.py`
- Modify: `include/config.h`
- Modify: `include/hw_init.h`

**Interfaces:**
- Consumes: N32L40x GPIO, ADC, I2C, UART, and RCC constants.
- Produces: `ACC_DET_*`, `ADC_CAR_*`, `BSP_I2C_*`, `DA218E_INT1_*`, GPS, EC800M, and debug UART board definitions.

- [ ] **Step 1: Write the failing source-contract test**

Create assertions that require PA12 ACC, PA3/ADC_CH_4 vehicle ADC, I2C2 on PD14/PD15 with `GPIO_AF1_I2C2`, PB3 DA218E INT1, PA0 light interrupt, and the confirmed UART/GPIO mappings. Also reject I2C1/PB6/PB7 as the accelerometer bus and reject PB0 ownership outside UART4.

- [ ] **Step 2: Run test and verify RED**

Run: `python tools/tests/test_hardware_pin_contract.py`

Expected: FAIL on the first stale mapping, currently `BSP_I2C I2C1`, `ADC_CAR_PIN GPIO_PIN_0`, or `ACC_DET_PIN GPIO_PIN_3`.

- [ ] **Step 3: Apply the minimal pin-map update**

Set:

```c
#define BSP_I2C I2C2
#define BSP_I2C_CLK RCC_APB1_PERIPH_I2C2
#define BSP_I2C_SDA_PORT GPIOD
#define BSP_I2C_SDA_PIN GPIO_PIN_14
#define BSP_I2C_SCL_PORT GPIOD
#define BSP_I2C_SCL_PIN GPIO_PIN_15
#define BSP_I2C_GPIO_AF GPIO_AF1_I2C2
#define DA218E_INT1_PORT GPIOB
#define DA218E_INT1_PIN GPIO_PIN_3
#define ADC_CAR_PORT GPIOA
#define ADC_CAR_PIN GPIO_PIN_3
#define ADC_CAR_CH ADC_CH_4
#define ACC_DET_PORT GPIOA
#define ACC_DET_PIN GPIO_PIN_12
```

Correct stale comments in `include/hw_init.h`; do not change public function signatures.

- [ ] **Step 4: Run test and verify GREEN**

Run: `python tools/tests/test_hardware_pin_contract.py`

Expected: `Hardware pin contract: PASS`.

---

### Task 2: Initialize I2C2, ADC_IN4, INT1, and independent GPS enable

**Files:**
- Modify: `tools/tests/test_hardware_pin_contract.py`
- Modify: `src/hw_init.c`
- Modify: `src/gps.c`

**Interfaces:**
- Consumes: board definitions from Task 1.
- Produces: `hw_gpio_init()`, `hw_i2c_init()`, `hw_adc_init()`, and `gps_enable(bool)` with non-overlapping ownership.

- [ ] **Step 1: Extend the test for initialization behavior**

Require `hw_i2c_init()` to use `BSP_I2C_GPIO_AF`, require PB3 input initialization, require PA3 analog initialization through `ADC_CAR_PIN`, and reject `GPIO_AF4_I2C1` from `gps_enable()`.

- [ ] **Step 2: Run test and verify RED**

Run: `python tools/tests/test_hardware_pin_contract.py`

Expected: FAIL because `gps_enable()` still switches PB6 to I2C1 and `hw_i2c_init()` hard-codes AF4.

- [ ] **Step 3: Apply minimal initialization changes**

Configure I2C2 at 100 kHz on PD14/PD15 using `BSP_I2C_GPIO_AF`. Configure PB3 as a no-pull digital input. Keep PA3 and PA1 in analog mode. Simplify `gps_enable()` to output push-pull high/low control plus existing bounded settle delays; never select an I2C AF on PB6.

- [ ] **Step 4: Run test and existing DA218E test**

Run:

```powershell
python tools/tests/test_hardware_pin_contract.py
python tools/tests/test_da218e_i2c_contract.py
python tools/tests/test_gps_tx_bounded.py
```

Expected: all print PASS.

---

### Task 3: Move ACC wake to the shared EXTI12 handler

**Files:**
- Modify: `tools/tests/test_hardware_pin_contract.py`
- Modify: `src/power_mgr.c`

**Interfaces:**
- Consumes: PA12 `ACC_DET_*` and PB15 `DC_UP_*` definitions.
- Produces: one `EXTI15_10_IRQHandler()` which independently services `EXTI_LINE12` and `EXTI_LINE15`.

- [ ] **Step 1: Extend the test for ACC/charge IRQ behavior**

Require PA12 to be configured with `GPIO_PIN_SOURCE12`, `EXTI_Trigger_Rising_Falling`, and `EXTI15_10_IRQn`. Require the shared ISR to test and clear both line 12 and line 15. Reject `EXTI3_IRQHandler` and `EXTI_LINE3` from the power manager.

- [ ] **Step 2: Run test and verify RED**

Run: `python tools/tests/test_hardware_pin_contract.py`

Expected: FAIL because the implementation still uses EXTI3 and lacks a shared handler.

- [ ] **Step 3: Implement the shared ISR**

Configure ACC for both edges so an ACC-on transition can wake STOP2 as well as an ACC-off transition. Replace the old EXTI3 handler with:

```c
void EXTI15_10_IRQHandler(void)
{
    if (EXTI_GetITStatus(EXTI_LINE12)) {
        EXTI_ClrITPendBit(EXTI_LINE12);
        pwr_acc_isr();
    }
    if (EXTI_GetITStatus(EXTI_LINE15)) {
        EXTI_ClrITPendBit(EXTI_LINE15);
        pwr_charge_isr();
    }
}
```

Clear `EXTI_LINE12` in STOP2 preparation. Keep high-level ACC polling and JT808 status unchanged because they already consume `ACC_DET_*`.

- [ ] **Step 4: Run test and power contract regression**

Run:

```powershell
python tools/tests/test_hardware_pin_contract.py
python tools/jt808_startup_no_fix_test.py
python tools/tests/test_power_stop2_contract.py
```

Expected: all applicable tests pass; if the existing STOP2 test encodes EXTI3, update that test to the confirmed PA12 contract and demonstrate its RED then GREEN result.

---

### Task 4: Add bounded startup hardware diagnostics

**Files:**
- Modify: `tools/tests/test_hardware_pin_contract.py`
- Modify: `src/main.c`

**Interfaces:**
- Consumes: initialized GPIO and USART1 debug output.
- Produces: a non-sensitive startup line identifying `ACC=PA12 CAR_ADC=PA3/CH4 I2C=I2C2/PD14/PD15` and the sampled `DA218E_INT1` level.

- [ ] **Step 1: Add a failing diagnostic assertion**

Require a stable `[HW]` banner and one `GPIO_ReadInputDataBit(DA218E_INT1_PORT, DA218E_INT1_PIN)` call after hardware initialization. Assert the banner contains no device identity or secret fields.

- [ ] **Step 2: Run test and verify RED**

Run: `python tools/tests/test_hardware_pin_contract.py`

Expected: FAIL because the `[HW]` banner is absent.

- [ ] **Step 3: Add the minimal diagnostic output**

Add one startup `dbg_printf()` after USART/GPIO initialization and before DA218E probing. Do not print from an ISR and do not add recurring main-loop logs.

- [ ] **Step 4: Run test and debug formatting regression**

Run:

```powershell
python tools/tests/test_hardware_pin_contract.py
python tools/tests/test_debug_printf_format.py
```

Expected: both PASS.

---

### Task 5: Full software verification and HIL handoff

**Files:**
- Modify only if a directly related test exposes a root-cause defect.

**Interfaces:**
- Consumes: completed Tasks 1-4.
- Produces: build/test evidence and an explicit HIL checklist; no flashed artifact.

- [ ] **Step 1: Run targeted host tests**

Run the four task-specific tests plus all existing tests whose names contain `da218e`, `gps`, `power`, `ec800m`, or `debug`.

- [ ] **Step 2: Build and run firmware guards**

Run:

```powershell
make all
make release-guard
make ram-guard
```

Expected: exit code 0 for each; record the first real failure otherwise.

- [ ] **Step 3: Check scope and whitespace**

Run:

```powershell
git diff --check
git status --short
git diff -- include/config.h include/hw_init.h src/hw_init.c src/gps.c src/power_mgr.c src/main.c tools/tests/test_hardware_pin_contract.py docs/superpowers/specs/2026-08-29-hardware-pin-bringup-design.md docs/superpowers/plans/2026-08-29-hardware-pin-bringup.md
```

Confirm that unrelated user changes remain untouched.

- [ ] **Step 4: Report unverified hardware checks**

Report as `需要实机/HIL验证`: PA12 ACC level and STOP2 wake, PA3 voltage calibration, PD14/PD15 I2C waveform and DA218E ID/data, PB3 INT1 level, UART4 NMEA, PB6 power control, UART5 AT traffic, PB7 DTR, and PA9 USART1 output.
