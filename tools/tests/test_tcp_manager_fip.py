#!/usr/bin/env python3
"""Host behavior test for enabling and disabling the JT808 backup endpoint."""

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[2]

HARNESS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include "tcp_manager.h"
#include "flash_config.h"
#include "fota.h"

volatile uint32_t g_tick_ms;
static device_config_t config;
static unsigned open_calls;
static unsigned close_calls;
static uint8_t last_channel;
static char last_ip[CFG_IP_LEN];
static uint16_t last_port;
static char log_text[1024];
static size_t log_length;
static char stub_imei[16] = "123456789012345";
static char stub_iccid[22] = "89860012345678901234";

device_config_t *cfg_get(void) { return &config; }
bool ec800m_is_ready(void) { return true; }
int ec800m_tcp_open(uint8_t channel, const char *ip, uint16_t port)
{
    ++open_calls;
    last_channel = channel;
    strncpy(last_ip, ip, sizeof(last_ip) - 1U);
    last_ip[sizeof(last_ip) - 1U] = '\0';
    last_port = port;
    return 0;
}
void ec800m_tcp_close(uint8_t channel) { (void)channel; ++close_calls; }
tcp_state_t ec800m_tcp_state(uint8_t channel)
{ (void)channel; return TCP_STATE_OPENING; }
void ec800m_get_imei(char *buf, uint8_t size) { snprintf(buf,size,"%s",stub_imei); }
void ec800m_get_iccid(char *buf, uint8_t size) { snprintf(buf,size,"%s",stub_iccid); }
int dbg_printf(const char *format, ...) {
    va_list args; int n; va_start(args,format);
    n=vsnprintf(log_text+log_length,sizeof(log_text)-log_length,format,args);va_end(args);
    if(n>0 && (size_t)n<sizeof(log_text)-log_length)log_length+=(size_t)n;
    return n;
}
fota_state_t fota_get_state(void) { return FOTA_STATE_IDLE; }

static void reset_endpoint(const char *backup, uint16_t port)
{
    memset(&config, 0, sizeof(config));
    strcpy(config.server_ip, "119.147.205.85");
    config.server_port = 9999U;
    if (backup != NULL) strcpy(config.backup_ip, backup);
    config.backup_port = port;
    open_calls = close_calls = 0U;
    last_channel = 0xffU;
    last_ip[0] = '\0';
    last_port = 0U;
    log_length = 0U; log_text[0] = '\0';
    tcp_manager_init();
    tcp_manager_process();
}

int main(void)
{
    reset_endpoint("", 7018U);
    assert(open_calls == 1U);
    assert(strstr(log_text,"[BOOT-ID] IMEI=123456789012345 PID=56789012345 ICCID=89860012345678901234\r\n")!=NULL);
    assert(strstr(log_text,"[BOOT-SERVER] MAIN=119.147.205.85:9999 BACKUP=OFF\r\n")!=NULL);
    assert(strstr(log_text,"[BOOT-ID]") < strstr(log_text,"[TCP] ch0 connecting"));
    tcp_manager_process();
    assert(strstr(strstr(log_text,"[BOOT-ID]")+1,"[BOOT-ID]")==NULL);

    strcpy(stub_imei, "123456789012");
    strcpy(stub_iccid, "898600123456");
    reset_endpoint("", 0U);
    assert(strstr(log_text,"[BOOT-ID] IMEI=INVALID(len=12) PID=INVALID ICCID=INVALID(len=12)\r\n")!=NULL);
    strcpy(stub_imei, "123456789012345");
    strcpy(stub_iccid, "89860012345678901234");

    strcpy(stub_iccid, "898604A1192490075609");
    reset_endpoint("", 0U);
    assert(strstr(log_text,"ICCID=898604A1192490075609\r\n")!=NULL);
    strcpy(stub_iccid, "89860012345678901234");

    reset_endpoint("58.61.154.237", 0U);
    assert(open_calls == 1U);

    reset_endpoint("58.61.154.237", 7018U);
    assert(open_calls == 2U);
    assert(last_channel == EC800M_CH_BACKUP);
    assert(strcmp(last_ip, "58.61.154.237") == 0 && last_port == 7018U);

    /* A valid hostname beginning with zero is not the disable sentinel. */
    reset_endpoint("0.example", 7018U);
    assert(open_calls == 2U);
    assert(last_channel == EC800M_CH_BACKUP);
    assert(strcmp(last_ip, "0.example") == 0 && last_port == 7018U);
    return 0;
}
'''


def compiler():
    for candidate in ("gcc", "cc"):
        found = shutil.which(candidate)
        if found:
            return found
        for directory in os.environ.get("PATH", "").split(os.pathsep):
            executable = pathlib.Path(directory) / (candidate + ".exe")
            if executable.is_file():
                return str(executable)
    return None


def main():
    cc = compiler()
    if cc is None:
        if os.environ.get("REQUIRE_GCC") == "1":
            print("test_tcp_manager_fip: FAIL (no C compiler available)")
            return 1
        print("test_tcp_manager_fip: SKIP (no C compiler available)")
        return 0
    with tempfile.TemporaryDirectory(prefix="tcp_manager_fip_") as directory:
        temp = pathlib.Path(directory)
        harness = temp / "harness.c"
        binary = temp / "harness.exe"
        harness.write_text(HARNESS, encoding="ascii")
        (temp / "n32l40x.h").write_text(
            "#ifndef N32L40X_H\n#define N32L40X_H\n#include <stdint.h>\n#endif\n",
            encoding="ascii",
        )
        command = [
            cc, "-std=c99", "-Wall", "-Wextra", "-Werror",
            "-I", str(temp), "-I", str(ROOT / "include"), str(harness),
            str(ROOT / "src" / "tcp_manager.c"), "-o", str(binary),
        ]
        built = subprocess.run(command, cwd=ROOT, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if built.returncode != 0:
            print(built.stdout, end="")
            print("test_tcp_manager_fip: FAIL (C harness did not compile)")
            return built.returncode
        run = subprocess.run([str(binary)], cwd=ROOT, text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if run.returncode != 0:
            print(run.stdout, end="")
            print("test_tcp_manager_fip: FAIL (C harness assertion)")
            return run.returncode
    print("test_tcp_manager_fip: C99 -Wall -Wextra -Werror PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
