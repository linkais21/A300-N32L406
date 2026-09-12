"""Host regression for the TCP manager's modem identity gate."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]

HEADERS = {
    "config.h": "#ifndef CONFIG_H\n#define CONFIG_H\n#define TCP_CH_MAIN 0U\n#define TCP_CH_BACKUP 3U\n#endif\n",
    "hw_init.h": "#ifndef HW_INIT_H\n#define HW_INIT_H\n#include <stdint.h>\nuint32_t host_tick(void);\n#define TICK_MS() host_tick()\n#endif\n",
    "debug_uart.h": "#ifndef DEBUG_UART_H\n#define DEBUG_UART_H\nint dbg_printf(const char *fmt, ...);\n#endif\n",
    "flash_config.h": r'''#ifndef FLASH_CONFIG_H
#define FLASH_CONFIG_H
#include <stdint.h>
typedef struct {
    char server_ip[64]; uint16_t server_port;
    char backup_ip[64]; uint16_t backup_port;
    char pid[12];
} device_config_t;
device_config_t *cfg_get(void);
#endif
''',
    "ec800m.h": r'''#ifndef EC800M_H
#define EC800M_H
#include <stdbool.h>
#include <stdint.h>
typedef enum { TCP_STATE_CLOSED=0, TCP_STATE_OPENING, TCP_STATE_OPEN, TCP_STATE_ERROR } tcp_state_t;
bool ec800m_is_ready(void);
bool ec800m_identity_ready(void);
int ec800m_tcp_open(uint8_t ch, const char *ip, uint16_t port);
void ec800m_tcp_close(uint8_t ch);
tcp_state_t ec800m_tcp_state(uint8_t ch);
void ec800m_get_imei(char *buf, uint8_t size);
void ec800m_get_iccid(char *buf, uint8_t size);
#endif
''',
    "fota.h": r'''#ifndef FOTA_H
#define FOTA_H
typedef enum { FOTA_STATE_IDLE=0, FOTA_STATE_CHECK_CONNECTING, FOTA_STATE_CHECKING,
FOTA_STATE_PREPARING, FOTA_STATE_CONNECTING, FOTA_STATE_DOWNLOADING,
FOTA_STATE_VERIFYING, FOTA_STATE_READY } fota_state_t;
fota_state_t fota_get_state(void);
#endif
''',
}

HARNESS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include "flash_config.h"
#include "ec800m.h"
#include "fota.h"
#include "tcp_manager.h"

static device_config_t config = { "127.0.0.1", 9000U, "", 0U, "12345678901" };
static bool modem_ready = true;
static bool identity_ready;
static tcp_state_t modem_tcp_state = TCP_STATE_OPENING;
static unsigned opens;
static unsigned closes;

uint32_t host_tick(void) { return 1000U; }
device_config_t *cfg_get(void) { return &config; }
bool ec800m_is_ready(void) { return modem_ready; }
bool ec800m_identity_ready(void) { return identity_ready; }
int ec800m_tcp_open(uint8_t ch, const char *ip, uint16_t port)
{ (void)ch; (void)ip; (void)port; ++opens; return 0; }
void ec800m_tcp_close(uint8_t ch) { (void)ch; ++closes; }
tcp_state_t ec800m_tcp_state(uint8_t ch) { (void)ch; return modem_tcp_state; }
void ec800m_get_imei(char *buf, uint8_t size)
{ if (size) { strncpy(buf, "123456789012345", size - 1U); buf[size - 1U] = '\0'; } }
void ec800m_get_iccid(char *buf, uint8_t size)
{ if (size) { strncpy(buf, "898604A1192490075609", size - 1U); buf[size - 1U] = '\0'; } }
fota_state_t fota_get_state(void) { return FOTA_STATE_IDLE; }
int dbg_printf(const char *fmt, ...) { (void)fmt; return 0; }

int main(void)
{
    tcp_manager_init();
    identity_ready = false;
    tcp_manager_process();
    assert(opens == 0U);
    identity_ready = true;
    tcp_manager_process();
    assert(opens == 1U);
    modem_tcp_state = TCP_STATE_OPEN;
    tcp_manager_process();
    assert(opens == 1U && closes == 0U);
    identity_ready = false;
    tcp_manager_process();
    assert(opens == 1U && closes == 1U);
    puts("test_tcp_identity_gate: PASS");
    return 0;
}
'''


def main() -> None:
    cc = os.environ.get("CC") or shutil.which("gcc") or shutil.which("cc")
    if not cc:
        raise AssertionError("host C compiler is required")
    with tempfile.TemporaryDirectory(prefix="tcp_identity_") as td:
        directory = Path(td)
        for name, content in HEADERS.items():
            (directory / name).write_text(content, encoding="ascii")
        harness = directory / "harness.c"
        output = directory / "tcp_identity.exe"
        harness.write_text(HARNESS, encoding="ascii")
        build = subprocess.run(
            [cc, "-std=c99", "-Wall", "-Wextra", "-Werror",
             "-I", str(directory), "-I", str(ROOT / "include"),
             str(harness), str(ROOT / "src" / "tcp_manager.c"),
             "-o", str(output)], cwd=ROOT, capture_output=True, text=True,
        )
        if build.returncode:
            raise AssertionError("TCP identity harness compile failed:\n" + build.stderr)
        run = subprocess.run([str(output)], cwd=ROOT,
                             capture_output=True, text=True)
        if run.returncode:
            raise AssertionError("TCP identity harness failed:\n" + run.stdout + run.stderr)
        print(run.stdout.strip())


if __name__ == "__main__":
    main()
