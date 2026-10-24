"""Host contract for EC800M NTP time-sync parsing and UTC conversion."""

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
typedef struct { uint32_t DUMMY; } dma_t;
typedef void GPIO_Module;
#define UART5 (&host_uart5)
#define EC800M_UART UART5
#define DMA_CH5 ((dma_t *)5)
#define DMA ((dma_t *)0)
#define DMA_FLAG_HT5 0x01U
#define DMA_FLAG_TC5 0x02U
#define USART_FLAG_TXDE 0x01U
#define USART_FLAG_TXC 0x02U
#define USART_FLAG_RXDNE 0x04U
#define USART_INT_RXDNE 0x08U
#define USART_FLAG_OREF 0x10U
#define RESET 0
#define SET 1
#define ENABLE 1
#define DISABLE 0
#define GPIOA ((GPIO_Module *)0x10)
#define GPIOB ((GPIO_Module *)0x11)
#define GPIO_PIN_7 7U
#define GPIO_PIN_8 8U
#define GPIO_PIN_15 15U
#define RCC_APB2_PERIPH_UART5 0U
extern usart_module_t host_uart5;
typedef int FlagStatus;
typedef int INTStatus;
uint32_t DMA_GetCurrDataCounter(dma_t *d);
FlagStatus DMA_GetFlagStatus(uint32_t flag, dma_t *d);
void DMA_ClearFlag(uint32_t flag, dma_t *d);
FlagStatus USART_GetFlagStatus(usart_module_t *u, uint16_t flag);
void USART_SendData(usart_module_t *u, uint16_t data);
uint16_t USART_ReceiveData(usart_module_t *u);
INTStatus USART_GetIntStatus(usart_module_t *u, uint16_t flag);
void IWDG_ReloadKey(void);
void GPIO_SetBits(GPIO_Module *p, uint16_t pin);
void GPIO_ResetBits(GPIO_Module *p, uint16_t pin);
int GPIO_ReadInputDataBit(GPIO_Module *p, uint16_t pin);
void delay_ms(uint32_t ms);
void delay_us(uint32_t us);
#endif
''',
    "config.h": r'''
#ifndef CONFIG_H
#define CONFIG_H
#include "n32l40x.h"
extern volatile uint32_t g_tick_ms;
#define TICK_MS() (g_tick_ms)
#define EC800M_RX_BUF_SIZE 1024U
#define EC800M_DMA_CH_RX ((dma_t *)8)
#define EC800M_POWER_EN_PORT GPIOA
#define EC800M_POWER_EN_PIN GPIO_PIN_15
#define EC800M_PWRKEY_PORT GPIOA
#define EC800M_PWRKEY_PIN GPIO_PIN_8
#define EC800M_DTR_PORT GPIOB
#define EC800M_DTR_PIN GPIO_PIN_7
#endif
''',
    "hw_init.h": r'''
#ifndef HW_INIT_H
#define HW_INIT_H
#include "n32l40x.h"
#endif
''',
    "debug_uart.h": r'''
#ifndef DEBUG_UART_H
#define DEBUG_UART_H
int dbg_printf(const char *fmt, ...);
void dbg_putchar(char c);
#endif
''',
    "peripherals.h": r'''
#ifndef PERIPHERALS_H
#define PERIPHERALS_H
#include <stdbool.h>
void sms_process_urc(const char *line);
void sms_send_complete(bool success);
#endif
''',
}


HARNESS = r'''
#include <assert.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "n32l40x.h"
#include "config.h"
#include "ec800m.h"
#include "flash_config.h"

volatile uint32_t g_tick_ms;
static device_config_t config;
device_config_t *cfg_get(void) { return &config; }
usart_module_t host_uart5;

bool ec800m_test_parse_qntp(const char *line, unsigned *year, unsigned *month,
                            unsigned *day, unsigned *hour, unsigned *minute,
                            unsigned *second, int *tz_quarter);
void ec800m_test_shift_minutes(uint16_t *year, uint8_t *month, uint8_t *day,
                               uint8_t *hour, uint8_t *minute, int offset_min);
void ec800m_test_qntp_time_to_utc(unsigned year, unsigned month, unsigned day,
                                  unsigned hour, unsigned minute,
                                  unsigned second, int tz_quarter,
                                  ec800m_time_t *out);

uint32_t DMA_GetCurrDataCounter(dma_t *d) { (void)d; return 0U; }
FlagStatus DMA_GetFlagStatus(uint32_t flag, dma_t *d) { (void)flag; (void)d; return RESET; }
void DMA_ClearFlag(uint32_t flag, dma_t *d) { (void)flag; (void)d; }
FlagStatus USART_GetFlagStatus(usart_module_t *u, uint16_t flag) { (void)u; (void)flag; return SET; }
void USART_SendData(usart_module_t *u, uint16_t data) { (void)u; (void)data; }
uint16_t USART_ReceiveData(usart_module_t *u) { (void)u; return 0U; }
INTStatus USART_GetIntStatus(usart_module_t *u, uint16_t flag) { (void)u; (void)flag; return RESET; }
void IWDG_ReloadKey(void) { ++g_tick_ms; }
void GPIO_SetBits(GPIO_Module *p, uint16_t pin) { (void)p; (void)pin; }
void GPIO_ResetBits(GPIO_Module *p, uint16_t pin) { (void)p; (void)pin; }
int GPIO_ReadInputDataBit(GPIO_Module *p, uint16_t pin) { (void)p; (void)pin; return SET; }
void delay_ms(uint32_t ms) { g_tick_ms += ms; }
void delay_us(uint32_t us) { (void)us; }
int dbg_printf(const char *fmt, ...) { (void)fmt; return 0; }
void dbg_putchar(char c) { (void)c; }
void sms_send_complete(bool success) { (void)success; }
void sms_process_urc(const char *line) { (void)line; }

int main(void)
{
    unsigned year, month, day, hour, minute, second;
    int tz_quarter;

    /* Well-formed URC, positive (east) timezone. */
    assert(ec800m_test_parse_qntp(
        "+QNTP: 0,\"2026/09/04,10:15:30+32\"",
        &year, &month, &day, &hour, &minute, &second, &tz_quarter));
    assert(year == 2026U && month == 9U && day == 4U);
    assert(hour == 10U && minute == 15U && second == 30U);
    assert(tz_quarter == 32);

    /* Negative (west) timezone offset. */
    assert(ec800m_test_parse_qntp(
        "+QNTP: 0,\"2026/01/01,00:05:00-20\"",
        &year, &month, &day, &hour, &minute, &second, &tz_quarter));
    assert(tz_quarter == -20);

    /* No timezone field at all (defaults to 0). */
    assert(ec800m_test_parse_qntp(
        "+QNTP: 0,\"2026/06/15,12:00:00\"",
        &year, &month, &day, &hour, &minute, &second, &tz_quarter));
    assert(tz_quarter == 0);

    /* err != 0 means the modem failed to sync: must be rejected. */
    assert(!ec800m_test_parse_qntp(
        "+QNTP: 1,\"2026/09/04,10:15:30+32\"",
        &year, &month, &day, &hour, &minute, &second, &tz_quarter));

    /* Wrong prefix, truncated line, and scanf-style partial junk must all
     * be rejected rather than silently accepted. */
    assert(!ec800m_test_parse_qntp(
        "+QIURC: \"recv\",0", &year, &month, &day, &hour, &minute, &second, &tz_quarter));
    assert(!ec800m_test_parse_qntp(
        "+QNTP: 0,\"2026/09/04,10:15", &year, &month, &day, &hour, &minute, &second, &tz_quarter));
    assert(!ec800m_test_parse_qntp(
        "+QNTP: 0,\"2026/09/04,10:15:30+32extra", &year, &month, &day, &hour, &minute, &second, &tz_quarter));

    /* Out-of-range month/day rejected even with otherwise valid syntax. */
    assert(!ec800m_test_parse_qntp(
        "+QNTP: 0,\"2026/00/04,10:15:30+32\"", &year, &month, &day, &hour, &minute, &second, &tz_quarter));
    assert(!ec800m_test_parse_qntp(
        "+QNTP: 0,\"2026/09/00,10:15:30+32\"", &year, &month, &day, &hour, &minute, &second, &tz_quarter));

    /* EC800M QNTP clock fields are already UTC. The suffix reports the modem
     * timezone setting and must not be applied a second time. This reproduces
     * the field capture: Beijing 16:52 corresponds to UTC 08:52, not 00:52. */
    {
        ec800m_time_t out;
        ec800m_test_qntp_time_to_utc(2026U, 9U, 10U, 8U, 52U, 52U,
                                     32, &out);
        assert(out.valid && out.year == 2026U && out.month == 9U &&
               out.day == 10U && out.hour == 8U && out.minute == 52U &&
               out.second == 52U);
        ec800m_test_qntp_time_to_utc(2026U, 1U, 1U, 0U, 5U, 0U,
                                     -20, &out);
        assert(out.year == 2026U && out.month == 1U && out.day == 1U &&
               out.hour == 0U && out.minute == 5U);
        ec800m_test_qntp_time_to_utc(2026U, 6U, 15U, 12U, 0U, 0U,
                                     0, &out);
        assert(out.hour == 12U && out.minute == 0U);
    }

    /* Generic calendar shifting remains independently tested for retained
     * clock rollover code; QNTP conversion no longer calls it. */
    {
        uint16_t y = 2026U; uint8_t mo = 9U, d = 4U, h = 10U, mi = 15U;
        ec800m_test_shift_minutes(&y, &mo, &d, &h, &mi, -32 * 15);
        assert(y == 2026U && mo == 9U && d == 4U && h == 2U && mi == 15U);
    }

    /* Backward day rollover: local 00:30 UTC+8 -> previous day 16:30 UTC. */
    {
        uint16_t y = 2026U; uint8_t mo = 3U, d = 1U, h = 0U, mi = 30U;
        ec800m_test_shift_minutes(&y, &mo, &d, &h, &mi, -32 * 15);
        assert(y == 2026U && mo == 2U && d == 28U && h == 16U && mi == 30U);
    }

    /* Backward month/year rollover across Jan 1 into prior year Dec 31. */
    {
        uint16_t y = 2026U; uint8_t mo = 1U, d = 1U, h = 3U, mi = 0U;
        ec800m_test_shift_minutes(&y, &mo, &d, &h, &mi, -8 * 60);
        assert(y == 2025U && mo == 12U && d == 31U && h == 19U && mi == 0U);
    }

    /* Forward rollover: local 23:50 UTC-5 (west) -> next day 04:50 UTC. */
    {
        uint16_t y = 2026U; uint8_t mo = 4U, d = 30U, h = 23U, mi = 50U;
        ec800m_test_shift_minutes(&y, &mo, &d, &h, &mi, 5 * 60);
        assert(y == 2026U && mo == 5U && d == 1U && h == 4U && mi == 50U);
    }

    /* Leap-year February rollover (2028 is a leap year). */
    {
        uint16_t y = 2028U; uint8_t mo = 3U, d = 1U, h = 0U, mi = 0U;
        ec800m_test_shift_minutes(&y, &mo, &d, &h, &mi, -60);
        assert(y == 2028U && mo == 2U && d == 29U && h == 23U && mi == 0U);
    }

    puts("test_ec800m_ntp_sync: PASS");
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
        print("test_ec800m_ntp_sync: SKIP (gcc/cc unavailable)")
        return
    with tempfile.TemporaryDirectory() as td:
        directory = pathlib.Path(td)
        for name, content in HEADERS.items():
            (directory / name).write_text(content, encoding="ascii")
        harness = directory / "harness.c"
        output = directory / "harness.exe"
        harness.write_text(HARNESS, encoding="ascii")
        command = [
            cc,
            "-std=c99",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-Wno-dangling-else",
            "-ffunction-sections",
            "-fdata-sections",
            "-DEC800M_HOST_TEST",
            "-I",
            str(directory),
            "-I",
            str(ROOT / "include"),
            str(harness),
            str(ROOT / "src" / "ec800m.c"),
            str(ROOT / "src" / "ec800m_at_response.c"),
            "-Wl,--gc-sections",
            "-o",
            str(output),
        ]
        build = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        if build.returncode:
            raise AssertionError("C harness compile failed:\n" + build.stderr)
        run = subprocess.run([str(output)], cwd=ROOT, capture_output=True, text=True)
        if run.returncode:
            raise AssertionError(
                "C harness failed (exit %d):\n%s\n%s"
                % (run.returncode, run.stdout, run.stderr)
            )
        print(run.stdout.strip())


if __name__ == "__main__":
    main()
