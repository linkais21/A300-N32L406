"""Host replay for bounded, deferred NMEA processing."""

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

/* This parser fixture has no stationary filter; keep trusted snapshots raw.
 * The production filter has its own regression scripts. */
bool gps_report_filter_copy(const gps_data_t *raw,gps_data_t *out,uint32_t now){(void)now;*out=*raw;return false;}

static void feed(const char *s){while(*s)gps_rx_isr((uint8_t)*s++);}

int main(void){
    const gps_data_t *g=gps_get_data();
    const volatile gps_diag_t *diag;
    feed("$GPRMC,123519,A,4807.038,N,01131.000,E,22.4,84.4,230394,003.1,W*6A\r\n");
    feed("$GPGGA,123520,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*4D\r\n");
    /* ISR only publishes: no navigation state changes until main loop. */
    assert(!g->valid);
    gps_process();
    assert(g->valid && g->hour==12U && g->minute==35U && g->second==19U);
    assert(fabs(g->lat-48.1173)<0.000001 && fabs(g->lon-11.5166666667)<0.000001);
    assert(fabsf(g->speed_kmh-41.4848f)<0.001f);
    gps_process();
    assert(g->second==20U && g->fix_quality==1U && g->satellites==8U);
    assert(fabsf(g->altitude_m-545.4f)<0.01f && fabsf(g->hdop-0.9f)<0.01f);
    {
        /* TAU804M documented GGA: geoid separation is legitimately empty. */
        uint32_t previous_update=g->last_update_ms;
        g_tick_ms+=100U;
        feed("$GPGGA,082006.000,3852.9276,N,11527.4283,E,1,08,1.0,20.6,M,,,,0000*35\r\n");
        gps_process();
        assert(g->last_update_ms!=previous_update);
        assert(g->valid && g->hour==8U && g->minute==20U && g->second==6U);
        assert(g->fix_quality==1U && g->satellites==8U);
        assert(fabs(g->lat-38.8821266667)<0.000001);
        assert(fabs(g->lon-115.4571383333)<0.000001);
        assert(fabsf(g->altitude_m-20.6f)<0.01f);
        assert(fabsf(g->geoid_sep_m)<0.001f);
    }
    {
        uint32_t previous_update=g->last_update_ms;
        uint8_t previous_second=g->second;
        g_tick_ms+=100U;
        feed("$GPRMC,123521,A,4807.038,N,01131.000,E,22.4junk,84.4,230394,003.1,W*7B\r\n");
        gps_process();
        /* A checksum-valid sentence with a partial numeric token is invalid. */
        assert(g->last_update_ms==previous_update && g->second==previous_second);
        feed("$GPRMC,123521.bad,A,4807.038,N,01131.000,E,22.4,84.4,230394,003.1,W*28\r\n");
        gps_process();
        assert(g->last_update_ms==previous_update && g->second==previous_second);
    }
    feed("$GPRMC,123519,A,4807.038,N,01131.000,E,22.4,84.4,230394,003.1,W*00\r\n");
    gps_process();
    feed("$GPGGA,123520,4807.038,N,01131.000,E,0,08,0.9,545.4,M,46.9,M,,*4C\r\n");
    gps_process();
    diag=gps_get_diag();
    assert(diag->sentences==7U);
    assert(diag->parsed==3U && diag->gga==3U && diag->rmc==3U);
    assert(diag->checksum_fail==1U && diag->format_fail==2U);
    assert(diag->no_fix==1U && diag->drop==0U);
    assert(diag->rx_bytes>0U);
    {
        uint32_t previous_parsed=diag->parsed;
        feed("$GPRMC,123519,A,4807.03800,N,01131.00000,E,22.4,84.4,230394,003.1,W*6A\r\n");
        gps_process();
        feed("$GPGGA,123520,4807.03800,N,01131.00000,E,1,08,0.9,545.4,M,46.9,M,,*4D\r\n");
        gps_process();
        /* TAU804M may emit five decimal minute digits; longitude then has 10 digits. */
        assert(diag->parsed==previous_parsed+2U);
        assert(fabs(g->lat-48.1173)<0.000001 && fabs(g->lon-11.5166666667)<0.000001);
    }
    {
        uint32_t previous_parsed=diag->parsed;
        uint32_t previous_format_fail=diag->format_fail;
        /* Zhongkewei GPS+BDS: GN talker, five decimal minute digits. */
        feed("$GNGGA,060210.000,3112.34567,N,12134.56789,E,1,12,0.8,35.0,M,-1.2,M,,*66\r\n");
        gps_process();
        feed("$GNRMC,060210.000,A,3112.34567,N,12134.56789,E,0.00,0.00,300426,,,A,V*0E\r\n");
        gps_process();
        /* Huada BDS: BD talker, five decimal minute digits. */
        feed("$BDGGA,025551.000,3112.34567,N,12134.56789,E,1,14,0.74,48.4,M,-1.2,M,,*59\r\n");
        gps_process();
        feed("$BDRMC,025551.000,A,3112.34567,N,12134.56789,E,0.10,15.0,300426,,,A,V*07\r\n");
        gps_process();
        /* Huada BDS RTK: GB talker, seven decimal minute digits. */
        feed("$GBGGA,055535.000,3112.3456789,N,12134.5678912,E,1,13,0.90,45.064,M,-1.170,M,,*5F\r\n");
        gps_process();
        feed("$GBRMC,055535.000,A,3112.3456789,N,12134.5678912,E,0.05,12.0,300426,,,A,V*00\r\n");
        gps_process();
        assert(diag->parsed==previous_parsed+6U);
        assert(diag->format_fail==previous_format_fail);
        assert(g->year==2026U && g->month==4U && g->day==30U);
        assert(fabs(g->lat-31.205761315)<0.00000001);
        assert(fabs(g->lon-121.57613152)<0.00000001);
    }
    {
        uint32_t previous_parsed=diag->parsed;
        uint32_t previous_format_fail=diag->format_fail;
        /* Zhongkewei BDS-only: empty course is a documented live format. */
        feed("$BDRMC,054247.00,A,3112.34567,N,12134.56789,E,0.17,,300426,,,A,V*2C\r\n");
        gps_process();
        assert(diag->parsed==previous_parsed+1U);
        assert(diag->format_fail==previous_format_fail);
        assert(fabsf(g->heading)<0.001f && g->year==2026U && g->month==4U && g->day==30U);
        feed("$BDRMC,054247.00,A,3112.34567,N,12134.56789,E,0.17,12junk,300426,,,A,V*35\r\n");
        gps_process();
        assert(diag->parsed==previous_parsed+1U);
        assert(diag->format_fail==previous_format_fail+1U);
    }
    return 0;
}
'''


def main() -> int:
    cc = os.environ.get("CC") or shutil.which("gcc") or shutil.which("clang")
    if not cc:
        print("test_nmea_replay: FAIL (host compiler required)")
        return 1
    with tempfile.TemporaryDirectory(prefix="nmea_replay_") as td:
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
    print("test_nmea_replay: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
