"""Host contract for bounded GPS UART transmission."""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[2]


HEADERS = {
    "n32l40x.h": r'''
#ifndef N32L40X_H
#define N32L40X_H
#include <stdint.h>
typedef struct { uint32_t DAT; } usart_module_t;
typedef struct { uint16_t Pin; uint8_t GPIO_Mode, GPIO_Slew_Rate, GPIO_Current, GPIO_Pull, GPIO_Alternate; } GPIO_InitType;
typedef void GPIO_Module;
extern usart_module_t host_uart4;
#define UART4 (&host_uart4)
#define GPIOB ((GPIO_Module *)0x1)
#define GPIO_PIN_0 0U
#define GPIO_PIN_1 1U
#define GPIO_PIN_6 6U
#define GPIO_Mode_Out_PP 1U
#define GPIO_Mode_AF_OD 2U
#define GPIO_Slew_Rate_High 1U
#define GPIO_DC_4mA 1U
#define GPIO_No_Pull 0U
#define GPIO_Pull_Up 1U
#define GPIO_AF4_I2C1 4U
#define USART_INT_RXDNE 1U
#define USART_FLAG_OREF 2U
#define USART_FLAG_TXDE 3U
#define USART_FLAG_TXC 4U
#define RESET 0
#define SET 1
#define Bit_RESET 0
typedef int FlagStatus;
typedef int INTStatus;
void GPIO_InitStruct(GPIO_InitType *g);
void GPIO_InitPeripheral(GPIO_Module *p, GPIO_InitType *g);
void GPIO_SetBits(GPIO_Module *p, uint16_t pin);
void GPIO_ResetBits(GPIO_Module *p, uint16_t pin);
INTStatus USART_GetIntStatus(usart_module_t *u, uint16_t flag);
FlagStatus USART_GetFlagStatus(usart_module_t *u, uint16_t flag);
uint16_t USART_ReceiveData(usart_module_t *u);
void USART_SendData(usart_module_t *u, uint16_t data);
void IWDG_ReloadKey(void);
#endif
''',
    "config.h": r'''
#ifndef CONFIG_H
#define CONFIG_H
#include "n32l40x.h"
extern volatile uint32_t g_tick_ms;
#define TICK_MS() (g_tick_ms)
#define GPS_UART UART4
#define GPS_TX_PORT GPIOB
#define GPS_TX_PIN GPIO_PIN_0
#define GPS_RX_PORT GPIOB
#define GPS_RX_PIN GPIO_PIN_1
#define GPS_EN_PORT GPIOB
#define GPS_EN_PIN GPIO_PIN_6
#endif
''',
}


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "n32l40x.h"
#include "gps.h"
#include "flash_config.h"
/* UART/ACK tests run with the optional report filter disabled. */
device_config_t *cfg_get(void) { return NULL; }
#include "i2c_accel.h"
bool i2c_accel_read(accel_data_t *out) { (void)out; return false; }

volatile uint32_t g_tick_ms;
usart_module_t host_uart4;
static int txde_ready = 1;
static int txc_ready = 1;
static int tick_advances = 1;
static unsigned reloads;
static unsigned tx_len;
static uint32_t txde_polls;
static uint32_t txde_release_after;
static uint32_t txde_block_after;
static uint32_t txde_wait_every;
static uint32_t txde_delayed_len;
static uint8_t tx_bytes[4096];

void GPIO_InitStruct(GPIO_InitType *g) { memset(g, 0, sizeof *g); }
void GPIO_InitPeripheral(GPIO_Module *p, GPIO_InitType *g) { (void)p; (void)g; }
void GPIO_SetBits(GPIO_Module *p, uint16_t pin) { (void)p; (void)pin; }
void GPIO_ResetBits(GPIO_Module *p, uint16_t pin) { (void)p; (void)pin; }
INTStatus USART_GetIntStatus(usart_module_t *u, uint16_t flag) { (void)u; (void)flag; return RESET; }
FlagStatus USART_GetFlagStatus(usart_module_t *u, uint16_t flag)
{
    (void)u;
    if (flag == USART_FLAG_TXDE) {
        ++txde_polls;
        if (!txde_ready || tx_len >= txde_block_after) {
            if (txde_release_after != 0U && txde_polls >= txde_release_after)
                return SET;
            return RESET;
        }
        if (txde_wait_every != 0U &&
            ((tx_len + 1U) % txde_wait_every) == 0U &&
            txde_delayed_len != tx_len) {
            txde_delayed_len = tx_len;
            return RESET;
        }
        return SET;
    }
    return flag == USART_FLAG_TXC ? (txc_ready ? SET : RESET) : SET;
}
uint16_t USART_ReceiveData(usart_module_t *u) { (void)u; return 0; }
void USART_SendData(usart_module_t *u, uint16_t data)
{
    (void)u;
    if (tx_len < sizeof tx_bytes) tx_bytes[tx_len++] = (uint8_t)data;
}
void IWDG_ReloadKey(void) { ++reloads; if (tick_advances) ++g_tick_ms; }
void delay_ms(uint32_t ms) { g_tick_ms += ms; }
void delay_us(uint32_t us) { (void)us; }

static void reset_uart(void)
{
    txde_ready = txc_ready = 1;
    tick_advances = 1;
    reloads = tx_len = 0;
    txde_polls = txde_release_after = txde_wait_every = 0U;
    txde_block_after = txde_delayed_len = UINT32_MAX;
    g_tick_ms = 0;
    memset(tx_bytes, 0, sizeof tx_bytes);
}

int main(void)
{
    const uint8_t bytes[] = { 0x00, 0x01, 0x7f, 0xff };
    reset_uart();
    assert(gps_send_raw(bytes, sizeof bytes) == 0);
    assert(tx_len == sizeof bytes && memcmp(tx_bytes, bytes, sizeof bytes) == 0);
    assert(reloads == 0U);

    reset_uart();
    txde_ready = 0;
    txde_release_after = 150000U;
    assert(gps_send_raw(bytes, sizeof bytes) < 0);
    assert(tx_len == 0 && reloads > 0);

    reset_uart();
    txde_block_after = 1U;
    assert(gps_send_raw(bytes, sizeof bytes) < 0);
    assert(tx_len == 1U && tx_bytes[0] == bytes[0]);

    reset_uart();
    txc_ready = 0;
    assert(gps_send_raw(bytes, sizeof bytes) < 0);
    assert(tx_len == sizeof bytes && reloads > 0);

    reset_uart();
    gps_send_cmd("XY");
    assert(tx_len == 2U && memcmp(tx_bytes, "XY", 2U) == 0);
    assert(reloads == 0U);

    reset_uart();
    txde_ready = 0;
    txde_release_after = 150000U;
    gps_send_cmd("X");
    assert(tx_len == 0 && reloads > 0);

    reset_uart();
    g_tick_ms = UINT32_MAX - 2U;
    txde_ready = 0;
    txde_release_after = 150000U;
    assert(gps_send_raw(bytes, sizeof bytes) < 0);
    assert(reloads > 0);

    reset_uart();
    tick_advances = 0;
    txde_ready = 0;
    txde_release_after = 150000U;
    assert(gps_send_raw(bytes, sizeof bytes) < 0);
    assert(tx_len == 0U && reloads > 0U);
    assert(txde_polls < txde_release_after);

    reset_uart();
    tick_advances = 0;
    txc_ready = 0;
    assert(gps_send_raw(bytes, sizeof bytes) < 0);
    assert(tx_len == sizeof bytes && reloads > 0U);

    {
        uint8_t long_bytes[1024];
        for (uint32_t i = 0U; i < sizeof long_bytes; ++i)
            long_bytes[i] = (uint8_t)i;
        reset_uart();
        txde_wait_every = 8U;
        assert(gps_send_raw(long_bytes, sizeof long_bytes) == 0);
        assert(tx_len == sizeof long_bytes);
        assert(memcmp(tx_bytes, long_bytes, sizeof long_bytes) == 0);
        assert(g_tick_ms == sizeof long_bytes / 8U);
    }

    puts("test_gps_tx_bounded: C harness PASS");
    return 0;
}
'''


def compiler() -> str | None:
    return os.environ.get("CC") or shutil.which("gcc") or shutil.which("cc")


def main() -> None:
    cc = compiler()
    if not cc:
        if os.environ.get("REQUIRE_GCC") == "1":
            raise AssertionError("REQUIRE_GCC=1 but no gcc/cc found")
        print("test_gps_tx_bounded: SKIP (gcc/cc unavailable)")
        return
    with tempfile.TemporaryDirectory() as td:
        directory = pathlib.Path(td)
        for name, content in HEADERS.items():
            (directory / name).write_text(content, encoding="ascii")
        harness = directory / "harness.c"
        output = directory / "harness.exe"
        harness.write_text(HARNESS + '\nint dbg_printf(const char *fmt,...){(void)fmt;return 0;}\n', encoding="ascii")
        command = [
            cc,
            "-std=c99",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-ffunction-sections",
            "-fdata-sections",
            "-I",
            str(directory),
            "-I",
            str(ROOT / "include"),
            str(harness),
            str(ROOT / "src" / "gps.c"),
            str(ROOT / "src" / "gps_report_filter.c"),
            "-Wl,--gc-sections",
            "-lm",
            "-o",
            str(output),
        ]
        build = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        if build.returncode:
            raise AssertionError("C harness compile failed:\n" + build.stderr)
        try:
            run = subprocess.run(
                [str(output)], cwd=ROOT, capture_output=True, text=True, timeout=15
            )
        except subprocess.TimeoutExpired as exc:
            raise AssertionError("C harness timed out; GPS TX is not bounded") from exc
        if run.returncode:
            raise AssertionError(
                "C harness failed (exit %d):\n%s\n%s"
                % (run.returncode, run.stdout, run.stderr)
            )
        print(run.stdout.strip())


if __name__ == "__main__":
    main()
