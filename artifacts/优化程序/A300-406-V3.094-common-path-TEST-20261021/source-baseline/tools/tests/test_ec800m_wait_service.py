"""Host regression for bounded GPS servicing during EC800M AT waits."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from test_ec800m_ntp_sync import HEADERS


ROOT = Path(__file__).resolve().parents[2]

HARNESS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include "n32l40x.h"
#include "flash_config.h"

volatile uint32_t g_tick_ms;
usart_module_t host_uart5;
static device_config_t config;
static uint32_t watchdog_calls;
static uint32_t service_calls;

device_config_t *cfg_get(void) { return &config; }
bool ec800m_test_wait_for_ok(uint32_t timeout_ms);
void ec800m_wait_service_hook(void) { ++service_calls; }
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
void IWDG_ReloadKey(void) { ++watchdog_calls; ++g_tick_ms; }
void GPIO_SetBits(GPIO_Module *p, uint16_t pin) { (void)p; (void)pin; }
void GPIO_ResetBits(GPIO_Module *p, uint16_t pin) { (void)p; (void)pin; }
int GPIO_ReadInputDataBit(GPIO_Module *p, uint16_t pin)
{ (void)p; (void)pin; return SET; }
void delay_ms(uint32_t ms) { g_tick_ms += ms; }
void delay_us(uint32_t us) { (void)us; }
int dbg_printf(const char *fmt, ...) { (void)fmt; return 0; }
void dbg_putchar(char c) { (void)c; }
void sms_process_urc(const char *line) { (void)line; }
void sms_send_complete(bool success) { (void)success; }

int main(void)
{
    assert(!ec800m_test_wait_for_ok(50U));
    assert(g_tick_ms >= 50U && g_tick_ms <= 51U);
    assert(watchdog_calls >= 50U);
    assert(service_calls == watchdog_calls);
    puts("test_ec800m_wait_service: PASS");
    return 0;
}
'''


def function_body(source: str, signature: str) -> str:
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[brace + 1:index]
    raise AssertionError(f"unterminated function: {signature}")


def main() -> None:
    cc = os.environ.get("CC") or shutil.which("gcc") or shutil.which("cc")
    if not cc:
        raise AssertionError("host C compiler is required")
    with tempfile.TemporaryDirectory(prefix="ec800m_wait_service_") as directory:
        temp = Path(directory)
        for name, content in HEADERS.items():
            (temp / name).write_text(content, encoding="ascii")
        (temp / "harness.c").write_text(HARNESS, encoding="ascii")
        output = temp / "harness.exe"
        command = [
            cc, "-std=c99", "-Wall", "-Wextra", "-Werror",
            "-Wno-dangling-else", "-DEC800M_HOST_TEST",
            "-I", str(temp), "-I", str(ROOT / "include"),
            str(temp / "harness.c"), str(ROOT / "src" / "ec800m.c"),
            str(ROOT / "src" / "ec800m_at_response.c"), "-o", str(output),
        ]
        built = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        if built.returncode:
            raise AssertionError("wait-service host build failed:\n" + built.stderr)
        run = subprocess.run([str(output)], cwd=ROOT, capture_output=True, text=True)
        if run.returncode:
            raise AssertionError("wait-service host run failed:\n" + run.stderr)

    main_source = (ROOT / "src" / "main.c").read_text(encoding="utf-8")
    body = function_body(main_source, "void ec800m_wait_service_hook")
    assert "gps_process();" in body
    for forbidden in ("ec800m_process", "jt808_process", "fota_process"):
        assert forbidden not in body
    print(run.stdout.strip())


if __name__ == "__main__":
    main()
