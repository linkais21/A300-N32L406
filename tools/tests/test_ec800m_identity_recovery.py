"""Host regression for bounded EC800M identity recovery."""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import tempfile

from test_ec800m_ntp_sync import HEADERS


ROOT = pathlib.Path(__file__).resolve().parents[2]


HARNESS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdarg.h>
#include "n32l40x.h"
#include "flash_config.h"

volatile uint32_t g_tick_ms;
usart_module_t host_uart5;
static device_config_t config;

device_config_t *cfg_get(void) { return &config; }
uint32_t DMA_GetCurrDataCounter(dma_t *d) { (void)d; return 1024U; }
FlagStatus DMA_GetFlagStatus(uint32_t flag, dma_t *d)
{ (void)flag; (void)d; return RESET; }
void DMA_ClearFlag(uint32_t flag, dma_t *d) { (void)flag; (void)d; }
FlagStatus USART_GetFlagStatus(usart_module_t *u, uint16_t flag)
{ (void)u; (void)flag; return SET; }
void USART_SendData(usart_module_t *u, uint16_t data)
{ (void)u; (void)data; }
uint16_t USART_ReceiveData(usart_module_t *u) { (void)u; return 0U; }
INTStatus USART_GetIntStatus(usart_module_t *u, uint16_t flag)
{ (void)u; (void)flag; return RESET; }
void IWDG_ReloadKey(void) { ++g_tick_ms; }
void GPIO_SetBits(GPIO_Module *p, uint16_t pin) { (void)p; (void)pin; }
void GPIO_ResetBits(GPIO_Module *p, uint16_t pin) { (void)p; (void)pin; }
int GPIO_ReadInputDataBit(GPIO_Module *p, uint16_t pin)
{ (void)p; (void)pin; return SET; }
void delay_ms(uint32_t ms) { g_tick_ms += ms; }
void delay_us(uint32_t us) { (void)us; }
int dbg_printf(const char *fmt, ...)
{ (void)fmt; return 0; }
void dbg_putchar(char c) { (void)c; }
void sms_process_urc(const char *line) { (void)line; }
void sms_send_complete(bool success) { (void)success; }

typedef enum {
    IDENTITY_QUERY_RETRY = 0,
    IDENTITY_QUERY_READY,
    IDENTITY_QUERY_RECOVER
} identity_query_result_t;

identity_query_result_t ec800m_test_identity_retry(bool valid,
                                                    uint8_t *attempts);
bool ec800m_test_identity_ready(const char *imei, const char *iccid);

int main(void)
{
    uint8_t attempts = 0U;

    assert(ec800m_test_identity_retry(true, &attempts) ==
           IDENTITY_QUERY_READY);
    assert(attempts == 0U);

    assert(ec800m_test_identity_retry(false, &attempts) ==
           IDENTITY_QUERY_RETRY);
    assert(attempts == 1U);
    assert(ec800m_test_identity_retry(true, &attempts) ==
           IDENTITY_QUERY_READY);
    assert(attempts == 0U);

    assert(ec800m_test_identity_retry(false, &attempts) ==
           IDENTITY_QUERY_RETRY);
    assert(ec800m_test_identity_retry(false, &attempts) ==
           IDENTITY_QUERY_RETRY);
    assert(ec800m_test_identity_retry(false, &attempts) ==
           IDENTITY_QUERY_RECOVER);
    assert(attempts == 3U);

    attempts = 2U;
    assert(ec800m_test_identity_retry(false, &attempts) ==
           IDENTITY_QUERY_RECOVER);
    assert(attempts == 3U);

    assert(ec800m_test_identity_ready("123456789012345",
                                      "898604A1192490075609"));
    assert(!ec800m_test_identity_ready("", "898604A1192490075609"));
    assert(!ec800m_test_identity_ready("12345678901234",
                                       "898604A1192490075609"));
    assert(!ec800m_test_identity_ready("123456789012345", ""));
    assert(!ec800m_test_identity_ready("123456789012345",
                                       "898604121025"));

    puts("test_ec800m_identity_recovery: PASS");
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
        print("test_ec800m_identity_recovery: SKIP (gcc/cc unavailable)")
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
                f"C harness failed (exit {run.returncode}):\n"
                f"{run.stdout}\n{run.stderr}"
            )
        print(run.stdout.strip())


if __name__ == "__main__":
    main()
