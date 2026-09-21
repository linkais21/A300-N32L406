"""Host contract for gps_apply_ntp_utc: NTP may only correct the retained
STOP1 fix's clock, never fabricate a fix or touch position/fix-validity."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]

N32 = r'''
#ifndef N32L40X_H
#define N32L40X_H
#include <stdint.h>
typedef void GPIO_Module;
typedef void USART_Module;
typedef struct { uint32_t Pin, GPIO_Mode, GPIO_Slew_Rate, GPIO_Current, GPIO_Pull; } GPIO_InitType;
#define UART4 ((USART_Module *)4)
#define GPIOB ((GPIO_Module *)2)
#define GPIO_PIN_0 1U
#define GPIO_PIN_6 2U
#define GPIO_Mode_Out_PP 1U
#define GPIO_Slew_Rate_High 1U
#define GPIO_DC_4mA 1U
#define GPIO_No_Pull 0U
#define USART_INT_RXDNE 1U
#define USART_FLAG_OREF 2U
#define USART_FLAG_TXDE 4U
#define USART_FLAG_TXC 8U
#define RESET 0
void GPIO_InitStruct(GPIO_InitType *g);
void GPIO_InitPeripheral(GPIO_Module *p, GPIO_InitType *g);
void GPIO_SetBits(GPIO_Module *p, uint32_t pin);
void GPIO_ResetBits(GPIO_Module *p, uint32_t pin);
int USART_GetIntStatus(USART_Module *u, uint32_t f);
int USART_GetFlagStatus(USART_Module *u, uint32_t f);
uint16_t USART_ReceiveData(USART_Module *u);
void USART_SendData(USART_Module *u, uint16_t d);
void IWDG_ReloadKey(void);
#endif
'''

CONFIG = r'''
#ifndef CONFIG_H
#define CONFIG_H
#include "n32l40x.h"
extern volatile uint32_t g_tick_ms;
#define TICK_MS() (g_tick_ms)
#define GPS_UART UART4
#define GPS_EN_PORT GPIOB
#define GPS_EN_PIN GPIO_PIN_6
#endif
'''

HARNESS = r'''
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "gps.h"
#include "n32l40x.h"

volatile uint32_t g_tick_ms = 1000U;
void GPIO_InitStruct(GPIO_InitType *g){memset(g,0,sizeof(*g));}
void GPIO_InitPeripheral(GPIO_Module *p, GPIO_InitType *g){(void)p;(void)g;}
void GPIO_SetBits(GPIO_Module *p,uint32_t pin){(void)p;(void)pin;}
void GPIO_ResetBits(GPIO_Module *p,uint32_t pin){(void)p;(void)pin;}
int USART_GetIntStatus(USART_Module *u,uint32_t f){(void)u;(void)f;return 0;}
int USART_GetFlagStatus(USART_Module *u,uint32_t f){(void)u;(void)f;return f==USART_FLAG_TXDE||f==USART_FLAG_TXC;}
uint16_t USART_ReceiveData(USART_Module *u){(void)u;return 0U;}
void USART_SendData(USART_Module *u,uint16_t d){(void)u;(void)d;}
void IWDG_ReloadKey(void){}
void delay_ms(uint32_t ms){g_tick_ms+=ms;}
int dbg_printf(const char *fmt,...){(void)fmt;return 0;}

static void feed(const char *s){while(*s)gps_rx_isr((uint8_t)*s++);}

int main(void){
    gps_data_t out;

    /* No trusted fix captured yet: apply must be a no-op (nothing to read
     * back, and no fix is fabricated). */
    gps_apply_ntp_utc(2026U, 9U, 4U, 2U, 15U, 30U);
    assert(!gps_get_last_trusted(&out));

    /* Establish a real trusted fix via the normal NMEA capture path. */
    feed("$GPRMC,123519,A,4807.038,N,01131.000,E,22.4,84.4,230394,003.1,W*6A\r\n");
    feed("$GPGGA,123520,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*4D\r\n");
    gps_process();
    gps_process();
    assert(gps_capture_last_trusted());
    assert(gps_get_last_trusted(&out));
    {
        double lat0 = out.lat, lon0 = out.lon;
        float speed0 = out.speed_kmh, heading0 = out.heading, alt0 = out.altitude_m;
        uint8_t fixq0 = out.fix_quality, sats0 = out.satellites;

        /* NTP correction: only the clock fields should change. */
        gps_apply_ntp_utc(2026U, 9U, 4U, 2U, 15U, 30U);
        assert(gps_get_last_trusted(&out));
        assert(out.year==2026U && out.month==9U && out.day==4U);
        assert(out.hour==2U && out.minute==15U && out.second==30U);
        assert(fabs(out.lat-lat0)<0.0000001 && fabs(out.lon-lon0)<0.0000001);
        assert(fabsf(out.speed_kmh-speed0)<0.001f);
        assert(fabsf(out.heading-heading0)<0.001f);
        assert(fabsf(out.altitude_m-alt0)<0.001f);
        assert(out.fix_quality==fixq0 && out.satellites==sats0);
    }

    /* Out-of-range fields must be rejected (no partial write). */
    gps_apply_ntp_utc(2026U, 13U, 4U, 2U, 15U, 30U);
    assert(gps_get_last_trusted(&out));
    assert(out.month==9U);
    gps_apply_ntp_utc(2026U, 9U, 4U, 25U, 15U, 30U);
    assert(gps_get_last_trusted(&out));
    assert(out.hour==2U);
    gps_apply_ntp_utc(1999U, 9U, 4U, 2U, 15U, 30U);
    assert(gps_get_last_trusted(&out));
    assert(out.year==2026U);

    puts("test_gps_ntp_apply: C harness PASS");
    return 0;
}
'''


def main() -> int:
    cc = os.environ.get("CC") or shutil.which("gcc") or shutil.which("clang")
    if not cc:
        print("test_gps_ntp_apply: FAIL (host compiler required)")
        return 1
    with tempfile.TemporaryDirectory(prefix="gps_ntp_") as td:
        d = Path(td)
        (d / "n32l40x.h").write_text(N32, encoding="ascii")
        (d / "config.h").write_text(CONFIG, encoding="ascii")
        (d / "hw_init.h").write_text('#include "n32l40x.h"\nvoid delay_ms(uint32_t);\n', encoding="ascii")
        (d / "debug_uart.h").write_text('int dbg_printf(const char*,...);\n', encoding="ascii")
        (d / "h.c").write_text(HARNESS, encoding="ascii")
        exe = d / "h.exe"
        cmd = [cc, "-std=c99", "-Wall", "-Wextra", "-Werror", "-I", str(d),
               "-I", str(ROOT / "include"), str(d / "h.c"),
               str(ROOT / "src/gps.c"), "-lm", "-o", str(exe)]
        built = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        if built.returncode:
            print(built.stdout + built.stderr, end="")
            return built.returncode
        run = subprocess.run([str(exe)], cwd=ROOT, capture_output=True, text=True)
        if run.returncode:
            print(run.stdout + run.stderr, end="")
            return run.returncode
    print("test_gps_ntp_apply: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
