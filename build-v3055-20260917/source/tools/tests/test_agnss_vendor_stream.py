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
static uint32_t gps_bytes;
static uint8_t gps_last[128];
static uint32_t gps_last_len;
static gps_data_t g = {0};
static device_config_t c = {"u", "p"};
int gps_send_raw(const uint8_t *p, uint32_t n) {
    assert(n <= sizeof gps_last);
    memcpy(gps_last, p, n); gps_last_len = n;
    ++gps_calls; gps_bytes += n; return fail_uart ? -1 : 0;
}
const gps_data_t *gps_get_data(void) { return &g; }
static fota_state_t ota_state=FOTA_STATE_IDLE;
fota_state_t fota_get_state(void) { return ota_state; }
bool ec800m_is_ready(void) { return true; }
tcp_state_t ec800m_tcp_state(uint8_t ch) { (void)ch; return TCP_STATE_OPEN; }
int ec800m_tcp_send(uint8_t ch, const uint8_t *p, uint16_t n) { (void)ch; (void)p; (void)n; return 0; }
device_config_t *cfg_get(void) { return &c; }

#include "agnss_huada.c"

static void make_huada_zero(uint8_t frame[8]) {
    frame[0] = 0xf1; frame[1] = 0xd9; frame[2] = 0x0b; frame[3] = 0x10;
    frame[4] = 0; frame[5] = 0; frame[6] = 0x1b; frame[7] = 0x5c;
}

int main(void) {
    uint8_t valid[8], oversized[8] = {0xf1, 0xd9, 0x0b, 0x10, 0xff, 0xff, 0, 0};
    make_huada_zero(valid);
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
    assert(agnss_huada_inject(&(agnss_source_t){valid, sizeof valid}, &(gps_context_t){0}) == 0);
    assert(gps_calls == 2);
    assert(agnss_huada_inject(&(agnss_source_t){oversized, sizeof oversized}, &(gps_context_t){0}) < 0);
    assert(agnss_huada_inject(&(agnss_source_t){valid, sizeof valid}, &(gps_context_t){0}) == 0);
    assert(gps_calls == 3);
    assert(agnss_huada_inject(&(agnss_source_t){valid, 3}, &(gps_context_t){0}) == 0);
    assert(gps_calls == 3);
    assert(agnss_huada_inject(&(agnss_source_t){valid + 3, 5}, &(gps_context_t){0}) == 0);
    assert(gps_calls == 4);
    assert(agnss_huada_inject(NULL, &(gps_context_t){0}) == 0);

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
