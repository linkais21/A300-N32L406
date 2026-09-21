#!/usr/bin/env python3
"""Host fault-injection coverage for DA218E INT1 configuration and re-arm."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]

HARNESS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "config.h"
#include "i2c_accel.h"

I2C_TypeDef fake_i2c;
static uint32_t tick_ms;
static unsigned data_count;
static unsigned write_count;
static unsigned fail_write;
static unsigned int1_reads;
static uint8_t current_reg;
static uint8_t write_regs[32];
static uint8_t write_values[32];
static bool receive_direction;
static uint8_t int1_level;

uint32_t test_tick_ms(void) { return tick_ms++; }
void delay_ms(uint32_t ms) { tick_ms += ms; }
void delay_us(uint32_t us) { (void)us; }
void hw_i2c_init(void) { }
int dbg_printf(const char *fmt, ...) { (void)fmt; return 0; }

void I2C_Enable(I2C_TypeDef *i2c, int enable)
{ (void)i2c; (void)enable; }
void I2C_EnableSoftwareReset(I2C_TypeDef *i2c, int enable)
{ (void)i2c; (void)enable; }
void I2C_GenerateStart(I2C_TypeDef *i2c, int enable)
{ (void)i2c; (void)enable; }
void I2C_GenerateStop(I2C_TypeDef *i2c, int enable)
{ (void)i2c; (void)enable; data_count = 0U; }
void I2C_SendAddr7bit(I2C_TypeDef *i2c, uint8_t addr, int direction)
{
    (void)i2c;
    (void)addr;
    receive_direction = direction == I2C_DIRECTION_RECV;
    data_count = 0U;
}
void I2C_SendData(I2C_TypeDef *i2c, uint8_t value)
{
    (void)i2c;
    ++data_count;
    if (data_count == 1U) {
        current_reg = value;
    } else if (data_count == 2U) {
        assert(write_count < sizeof write_regs);
        write_regs[write_count] = current_reg;
        write_values[write_count] = value;
        ++write_count;
    }
}
int I2C_CheckEvent(I2C_TypeDef *i2c, uint32_t event)
{
    (void)i2c;
    if (event == I2C_EVT_MASTER_DATA_SENDED && data_count == 2U &&
        fail_write != 0U && write_count == fail_write)
        return 0;
    return 1;
}
int I2C_GetFlag(I2C_TypeDef *i2c, uint32_t flag)
{ (void)i2c; (void)flag; return 1; }
void I2C_ConfigAck(I2C_TypeDef *i2c, int enable)
{ (void)i2c; (void)enable; }
uint8_t I2C_RecvData(I2C_TypeDef *i2c)
{
    (void)i2c;
    return receive_direction ? 0x13U : 0U;
}

void GPIO_InitStruct(GPIO_InitType *gpio) { memset(gpio, 0, sizeof *gpio); }
void GPIO_InitPeripheral(void *port, const GPIO_InitType *gpio)
{ (void)port; (void)gpio; }
void GPIO_SetBits(void *port, uint32_t pin) { (void)port; (void)pin; }
void GPIO_ResetBits(void *port, uint32_t pin) { (void)port; (void)pin; }
int GPIO_ReadInputDataBit(void *port, uint32_t pin)
{
    if (port == DA218E_INT1_PORT && pin == DA218E_INT1_PIN) {
        ++int1_reads;
        return int1_level ? Bit_SET : Bit_RESET;
    }
    return Bit_SET;
}

static void reset_bus(unsigned failing_write, uint8_t pb3_level)
{
    memset(&fake_i2c, 0, sizeof fake_i2c);
    memset(write_regs, 0, sizeof write_regs);
    memset(write_values, 0, sizeof write_values);
    tick_ms = 0U;
    data_count = 0U;
    write_count = 0U;
    fail_write = failing_write;
    int1_reads = 0U;
    current_reg = 0U;
    receive_direction = false;
    int1_level = pb3_level;
}

static void expect_init(bool expected_ok)
{
    const accel_diag_t *diag;
    i2c_accel_init();
    diag = i2c_accel_get_diag();
    assert(diag->address == DA218E_I2C_ADDR);
    assert(diag->int1_rearm_ok == expected_ok);
    assert(!diag->vibration_hit);
    assert(int1_reads == 1U);
}

int main(void)
{
    reset_bus(0U, 1U);
    expect_init(true);
    assert(write_count == 12U);
    const uint8_t expected_regs[] = {0x0F,0x10,0x11,0x20,0x20,0x16,0x19,0x21,0x27,0x28,0x20,0x20};
    const uint8_t expected_values[] = {0x00,0x07,0x00,0x81,0x01,0x83,0x04,0x07,0x00,0x26,0x81,0x01};
    assert(!memcmp(write_regs,expected_regs,sizeof expected_regs));
    assert(!memcmp(write_values,expected_values,sizeof expected_values));
    assert(write_regs[10] == 0x20U && write_values[10] == 0x81U);
    assert(write_regs[11] == 0x20U && write_values[11] == 0x01U);
    assert(i2c_accel_get_diag()->int1_level == 1U);

    reset_bus(1U, 0U);   /* RANGE */
    expect_init(false);

    reset_bus(7U, 0U);   /* INT_MAP1 */
    expect_init(false);

    reset_bus(11U, 0U);  /* final Reset_int write */
    expect_init(false);

    reset_bus(12U, 0U);  /* final restore write */
    expect_init(false);

    for(unsigned cut=1;cut<=12;cut++) {
        reset_bus(cut,0U);expect_init(false);
        assert(write_count==cut); /* no later register write after failure */
        assert(!memcmp(write_regs,expected_regs,cut));
        assert(!memcmp(write_values,expected_values,cut));
    }

    puts("test_i2c_accel_int1_rearm: PASS");
    return 0;
}
'''

HEADERS = {
    "config.h": r'''#ifndef CONFIG_H
#define CONFIG_H
#include "n32l40x.h"
#define BSP_I2C (&fake_i2c)
#define BSP_I2C_SCL_PORT ((void *)1)
#define BSP_I2C_SDA_PORT ((void *)2)
#define BSP_I2C_SCL_PIN 0x4000U
#define BSP_I2C_SDA_PIN 0x8000U
#define DA218E_INT1_PORT ((void *)3)
#define DA218E_INT1_PIN 0x0008U
#define DA218E_I2C_ADDR 0x26U
#define DA218E_I2C_FALLBACK_ADDR 0x27U
#define DA218E_I2C_LEGACY_ADDR 0x13U
#define DA218E_I2C_LEGACY_FALLBACK_ADDR 0x12U
#endif
''',
    "hw_init.h": r'''#ifndef HW_INIT_H
#define HW_INIT_H
#include <stdint.h>
uint32_t test_tick_ms(void);
#define TICK_MS() test_tick_ms()
void delay_ms(uint32_t ms);
void delay_us(uint32_t us);
void hw_i2c_init(void);
#endif
''',
    "debug_uart.h": "#ifndef DEBUG_UART_H\n#define DEBUG_UART_H\nint dbg_printf(const char *fmt, ...);\n#endif\n",
    "n32l40x.h": r'''#ifndef N32L40X_H
#define N32L40X_H
#include <stdint.h>
typedef struct { uint32_t CTRL1, STS1, STS2; } I2C_TypeDef;
extern I2C_TypeDef fake_i2c;
typedef struct {
    uint32_t Pin, GPIO_Mode, GPIO_Slew_Rate, GPIO_Current, GPIO_Pull;
} GPIO_InitType;
#define ENABLE 1
#define DISABLE 0
#define RESET 0
#define Bit_RESET 0
#define Bit_SET 1
#define GPIO_Mode_Out_OD 1U
#define GPIO_Slew_Rate_High 1U
#define GPIO_DC_4mA 1U
#define GPIO_Pull_Up 1U
#define GPIOD ((void *)4)
#define I2C_DIRECTION_SEND 0
#define I2C_DIRECTION_RECV 1
#define I2C_EVT_MASTER_MODE_FLAG 1U
#define I2C_EVT_MASTER_TXMODE_FLAG 2U
#define I2C_EVT_MASTER_DATA_SENDING 3U
#define I2C_EVT_MASTER_DATA_SENDED 4U
#define I2C_FLAG_ADDRF 5U
#define I2C_FLAG_BYTEF 6U
#define I2C_FLAG_RXDATNE 7U
void I2C_Enable(I2C_TypeDef *, int);
void I2C_EnableSoftwareReset(I2C_TypeDef *, int);
void I2C_GenerateStart(I2C_TypeDef *, int);
void I2C_GenerateStop(I2C_TypeDef *, int);
void I2C_SendAddr7bit(I2C_TypeDef *, uint8_t, int);
void I2C_SendData(I2C_TypeDef *, uint8_t);
int I2C_CheckEvent(I2C_TypeDef *, uint32_t);
int I2C_GetFlag(I2C_TypeDef *, uint32_t);
void I2C_ConfigAck(I2C_TypeDef *, int);
uint8_t I2C_RecvData(I2C_TypeDef *);
void GPIO_InitStruct(GPIO_InitType *);
void GPIO_InitPeripheral(void *, const GPIO_InitType *);
void GPIO_SetBits(void *, uint32_t);
void GPIO_ResetBits(void *, uint32_t);
int GPIO_ReadInputDataBit(void *, uint32_t);
#endif
''',
}


def main() -> None:
    cc = os.environ.get("CC") or shutil.which("gcc") or shutil.which("cc")
    if not cc:
        raise AssertionError("host C compiler is required")
    with tempfile.TemporaryDirectory(prefix="da218e_int1_") as td:
        directory = Path(td)
        for name, content in HEADERS.items():
            (directory / name).write_text(content, encoding="ascii")
        harness = directory / "harness.c"
        binary = directory / "da218e_int1.exe"
        harness.write_text(HARNESS, encoding="ascii")
        build = subprocess.run(
            [cc, "-std=c99", "-Wall", "-Wextra", "-Werror",
             "-I", str(directory), "-I", str(ROOT / "include"),
             str(harness), str(ROOT / "src" / "i2c_accel.c"),
             str(ROOT / "src" / "accel_vibration_filter.c"),
             "-o", str(binary)],
            cwd=ROOT, capture_output=True, text=True,
        )
        if build.returncode:
            raise AssertionError("DA218E harness compile failed:\n" + build.stderr)
        run = subprocess.run([str(binary)], cwd=ROOT,
                             capture_output=True, text=True)
        if run.returncode:
            raise AssertionError("DA218E harness failed:\n" + run.stdout + run.stderr)
        print(run.stdout.strip())


if __name__ == "__main__":
    main()
