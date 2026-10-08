"""Compile/execute the Task 6 vendor stream reset contract."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def _write_harness_headers(directory):
    headers = {
        "agnss_storage.h": """#ifndef AGNSS_STORAGE_H
#define AGNSS_STORAGE_H
#include <stdint.h>
typedef enum { GNSS_TYPE_UNKNOWN=0, GNSS_TYPE_TAU804M=1, GNSS_TYPE_ATGM332D_F7N=2 } gnss_type_t;
#endif
""",
        "gps.h": """#ifndef GPS_H
#define GPS_H
#include <stdint.h>
#include <stdbool.h>
typedef struct { double lat, lon; float altitude_m; uint16_t year; uint8_t month, day, hour, minute, second; bool valid; } gps_data_t;
typedef gps_data_t gps_context_t;
int gps_send_raw(const uint8_t *, uint32_t);
const gps_data_t *gps_get_data(void);
void gps_get_unfixed_report(gps_data_t *);
uint32_t gps_agnss_ack_sequence(void);
bool gps_agnss_take_ack(uint32_t *, uint8_t[10]);
#endif
""",
        "config.h": """#ifndef CONFIG_H
#define CONFIG_H
#include <stdint.h>
extern uint32_t tick;
#define TICK_MS() tick
#endif
""",
        "agnss_vendor.h": """#ifndef AGNSS_VENDOR_H
#define AGNSS_VENDOR_H
#include <stdint.h>
#include <stdbool.h>
#include "agnss_storage.h"
#include "gps.h"
typedef struct { const uint8_t *data; uint32_t len; } agnss_source_t;
int agnss_huada_inject(const agnss_source_t *, const gps_context_t *);
#endif
""",
        "debug_uart.h": "#ifndef DEBUG_UART_H\n#define DEBUG_UART_H\n#endif\n",
        "ec800m.h": """#ifndef EC800M_H
#define EC800M_H
#include <stdint.h>
#include <stdbool.h>
#define EC800M_CH_AGPS 2
typedef enum { TCP_STATE_CLOSED=0, TCP_STATE_OPEN=2 } tcp_state_t;
bool ec800m_is_ready(void); tcp_state_t ec800m_tcp_state(uint8_t); int ec800m_tcp_send(uint8_t, const uint8_t *, uint16_t);
#endif
""",
        "flash_config.h": """#ifndef FLASH_CONFIG_H
#define FLASH_CONFIG_H
typedef struct { char agnss_user[64], agnss_pwd[64]; } device_config_t;
device_config_t *cfg_get(void);
#endif
""",
    }
    for name, content in headers.items():
        (directory / name).write_text(content, encoding="ascii")


def _write_harness(directory):
    (directory / "harness.c").write_text(r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include "agnss_vendor.h"
#include "flash_config.h"
#include "ec800m.h"
#include "fota.h"

static int fail_uart;
static unsigned gps_calls;
static uint32_t cold_done;
extern uint32_t tick;
static uint32_t gps_bytes;
static uint8_t gps_last[128];
static uint32_t gps_last_len;
static gps_data_t g = {0};
static device_config_t c = {"u", "p"};
int gps_send_raw(const uint8_t *p, uint32_t n) {
    assert(n <= sizeof gps_last);
    if(p[2]==6 && p[3]==0x40){tick+=7;cold_done=tick;}
    else assert((uint32_t)(tick-cold_done)>=1000U);
    memcpy(gps_last, p, n); gps_last_len = n;
    ++gps_calls; gps_bytes += n; return fail_uart ? -1 : 0;
}
const gps_data_t *gps_get_data(void) { return &g; }
uint32_t tick;
static uint32_t ack_seq;
static int ack_ready;
static uint8_t ack_frame[10];
uint32_t gps_agnss_ack_sequence(void) { return ack_seq; }
bool gps_agnss_take_ack(uint32_t *seq, uint8_t out[10]) {
    if (!ack_ready || *seq == ack_seq) return false;
    memcpy(out, ack_frame, sizeof ack_frame);
    *seq = ack_seq; ack_ready = 0; return true;
}
void gps_get_unfixed_report(gps_data_t *out) { *out = g; }
static fota_state_t ota_state=FOTA_STATE_IDLE;
fota_state_t fota_get_state(void) { return ota_state; }
bool ec800m_is_ready(void) { return true; }
tcp_state_t ec800m_tcp_state(uint8_t ch) { (void)ch; return TCP_STATE_OPEN; }
int ec800m_tcp_send(uint8_t ch, const uint8_t *p, uint16_t n) { (void)ch; (void)p; (void)n; return 0; }
device_config_t *cfg_get(void) { return &c; }

#include "agnss_huada.c"

static void make_bds(uint8_t frame[100]) {
    memset(frame, 0, 100); frame[0]=0xf1; frame[1]=0xd9; frame[2]=0x0b;
    frame[3]=0x33; frame[4]=0x5c; frame[5]=0x00;
    uint8_t a=0,b=0; for (unsigned i=2;i<98;i++){a=(uint8_t)(a+frame[i]);b=(uint8_t)(b+a);} frame[98]=a; frame[99]=b;
}
static void make_ack(uint8_t ok) {
    memset(ack_frame,0,sizeof ack_frame); ack_frame[0]=0xf1;ack_frame[1]=0xd9;
    ack_frame[2]=5;ack_frame[3]=ok;ack_frame[4]=2;ack_frame[6]=0x0b;ack_frame[7]=0x33;
    uint8_t a=0,b=0; for(unsigned i=2;i<8;i++){a=(uint8_t)(a+ack_frame[i]);b=(uint8_t)(b+a);} ack_frame[8]=a;ack_frame[9]=b;
    ++ack_seq; ack_ready=1;
}

static int settled_inject(const uint8_t *data,uint32_t len,const gps_context_t *ctx){
    unsigned before=gps_calls;
    int result=agnss_huada_inject(&(agnss_source_t){data,len},ctx);
    if(gps_calls==before+1 && gps_last[2]==6){
        assert(result==1 && gnss_vendor_inject_pending());
        for(unsigned i=0;i<10;i++)assert(agnss_huada_inject(&(agnss_source_t){data,len},ctx)==1);
        tick+=999;assert(agnss_huada_inject(&(agnss_source_t){data,len},ctx)==1);
        assert(gps_calls==before+1);
        tick++;result=agnss_huada_inject(&(agnss_source_t){data,len},ctx);
    }
    return result;
}
int main(void) {
    uint8_t valid[100], oversized[8] = {0xf1, 0xd9, 0x0b, 0x10, 0xff, 0xff, 0, 0};
    make_bds(valid);
    /* Retired receiver must never forward even a valid legacy CSIP frame. */
    { uint8_t legacy[30] = {0xba,0xce,20,0,8,0};
      legacy[26]=20; legacy[28]=8;
      assert(!gnss_vendor_inject(GNSS_TYPE_ATGM332D_F7N,legacy,sizeof legacy));
      gnss_vendor_set_type(GNSS_TYPE_ATGM332D_F7N);
      assert(!gnss_vendor_network_rx(EC800M_CH_AGPS,legacy,sizeof legacy));
      assert(gps_calls==0);
    }

    { const fota_state_t active[]={FOTA_STATE_CONNECTING,FOTA_STATE_DOWNLOADING,FOTA_STATE_VERIFYING,FOTA_STATE_READY,FOTA_STATE_CHECK_CONNECTING,FOTA_STATE_CHECKING,FOTA_STATE_PREPARING};
      gnss_vendor_set_type(GNSS_TYPE_TAU804M);
      for(unsigned i=0;i<sizeof active/sizeof active[0];i++){
        ota_state=active[i];assert(!gnss_vendor_network_rx(EC800M_CH_AGPS,valid,sizeof valid));assert(gps_calls==0);
      }
      ota_state=FOTA_STATE_IDLE;
    }
    fail_uart = 1;
    assert(agnss_huada_inject(&(agnss_source_t){valid, sizeof valid}, &(gps_context_t){0}) < 0);
    assert(gps_calls == 1);
    fail_uart = 0;
    assert(settled_inject(valid, sizeof valid, &(gps_context_t){0}) == 1);
    /* A new transaction starts with cold start, then sends its first BDS frame. */
    assert(gps_calls == 3 && gnss_vendor_inject_pending());
    make_ack(1);
    assert(agnss_huada_inject(&(agnss_source_t){valid, sizeof valid}, &(gps_context_t){0}) == 0);
    assert(gps_calls == 3 && !gnss_vendor_inject_pending());
    assert(agnss_huada_inject(&(agnss_source_t){oversized, sizeof oversized}, &(gps_context_t){0}) < 0);
    assert(settled_inject(valid, sizeof valid, &(gps_context_t){0}) == 1);
    make_ack(1);
    assert(agnss_huada_inject(&(agnss_source_t){valid, sizeof valid}, &(gps_context_t){0}) == 0);
    assert(gps_calls == 5);
    assert(agnss_huada_inject(NULL, &(gps_context_t){0}) == 0);

    /* No ACK keeps the caller pending; NAK and timeout fail closed. */
    make_bds(valid);tick=0;
    assert(settled_inject(valid, sizeof valid, &(gps_context_t){0}) == 1);
    assert(gnss_vendor_inject_pending());
    tick+=1000;
    assert(agnss_huada_inject(&(agnss_source_t){valid, sizeof valid}, &(gps_context_t){0}) < 0);
    assert(!gnss_vendor_inject_pending());
    assert(settled_inject(valid, sizeof valid, &(gps_context_t){0}) == 1);
    make_ack(0);
    assert(agnss_huada_inject(&(agnss_source_t){valid, sizeof valid}, &(gps_context_t){0}) < 0);
    assert(!gnss_vendor_inject_pending());

    /* Reset after failure restarts cold settle, including tick wrap. */
    tick=UINT32_MAX-100U;
    assert(settled_inject(valid,sizeof valid,&(gps_context_t){0})==1);
    make_ack(1);assert(agnss_huada_inject(&(agnss_source_t){valid,sizeof valid},&(gps_context_t){0})==0);
    assert(agnss_huada_inject(NULL,&(gps_context_t){0})==0);
    /* Metadata is obtained at actual TX, after the cold settle window. */
    g.year=2026;g.month=10;g.day=8;g.second=1;
    assert(agnss_huada_inject(&(agnss_source_t){valid,sizeof valid},&(gps_context_t){0})==1);
    unsigned pending_calls=gps_calls;
    tick+=999;g.second=2;
    assert(agnss_huada_inject(&(agnss_source_t){valid,sizeof valid},&(gps_context_t){0})==1);
    assert(gps_calls==pending_calls);
    tick++;assert(agnss_huada_inject(&(agnss_source_t){valid,sizeof valid},&(gps_context_t){0})==1);
    assert(gps_last[3]==0x11 && gps_last[15]==2);
    huada_reset_stream();assert(!gnss_vendor_inject_pending());g.year=0;
    /* Position rounding is away from zero; negative MSL altitude is signed. */
    gps_context_t loc={0};loc.valid=true;loc.lat=-0.00000005;loc.lon=180;loc.altitude_m=-12.5f;
    assert(build_location(&loc,gps_last)==25);
    assert(gps_last[7]==0xff && gps_last[8]==0xff && gps_last[9]==0xff && gps_last[10]==0xff);
    assert(gps_last[15]==0x1e && gps_last[16]==0xfb && gps_last[17]==0xff && gps_last[18]==0xff);
    loc.lat=91;unsigned before=gps_calls;assert(build_location(&loc,gps_last)==0 && gps_calls==before);
    loc.lat=NAN;assert(build_location(&loc,gps_last)==0 && gps_calls==before);
    loc.lat=0;loc.altitude_m=21474836.0f;assert(build_location(&loc,gps_last)==0 && gps_calls==before);

    return 0;
}
''', encoding="ascii")


def test_c_harness():
    # In Windows shells PATHEXT may be absent in Python's child environment;
    # accept an explicit compiler path so the real C contract cannot silently
    # downgrade to a skip.
    compiler = os.environ.get("CC") or shutil.which("gcc") or shutil.which("cc")
    if not compiler:
        if os.environ.get("REQUIRE_GCC") == "1":
            raise AssertionError("REQUIRE_GCC=1 but no gcc/cc found")
        print("test_agnss_vendor_stream: SKIP (gcc/cc unavailable)")
        return
    with tempfile.TemporaryDirectory() as td:
        directory = Path(td)
        _write_harness_headers(directory)
        _write_harness(directory)
        output = directory / "harness.exe"
        build = subprocess.run([
            compiler, "-std=c99", "-I", str(directory),
            "-I", str(ROOT / "include"), "-I", str(ROOT / "src"),
            str(directory / "harness.c"),
            str(ROOT / "src" / "agnss_stream_workspace.c"),
            str(ROOT / "src" / "huada_ack.c"),
            "-o", str(output), "-lm"
        ], cwd=ROOT, capture_output=True, text=True)
        if build.returncode:
            raise AssertionError("C harness compile failed:\n" + build.stderr)
        run = subprocess.run([str(output)], cwd=ROOT, capture_output=True, text=True)
        if run.returncode:
            raise AssertionError("C harness failed (exit %d):\n%s" % (run.returncode, run.stderr))
        print("test_agnss_vendor_stream: C harness PASS")


if __name__ == "__main__":
    test_c_harness()
    print("test_agnss_vendor_stream: PASS")
