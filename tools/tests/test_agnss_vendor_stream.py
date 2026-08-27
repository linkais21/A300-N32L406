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
typedef enum { ZK_RESP_MALFORMED=-1, ZK_RESP_INCOMPLETE=0, ZK_RESP_OK=1 } zhongkewei_resp_t;
int agnss_huada_inject(const agnss_source_t *, const gps_context_t *);
int agnss_zhongkewei_request(const agnss_source_t *, const gps_context_t *);
zhongkewei_resp_t zhongkewei_parse_response(const uint8_t *, uint32_t, const uint8_t **, uint16_t *);
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
        "fota.h": """#ifndef FOTA_H
#define FOTA_H
typedef enum { FOTA_STATE_IDLE=0, FOTA_STATE_CONNECTING, FOTA_STATE_DOWNLOADING, FOTA_STATE_VERIFYING } fota_state_t;
fota_state_t fota_get_state(void);
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
static gps_data_t g = {0};
static device_config_t c = {"u", "p"};
int gps_send_raw(const uint8_t *p, uint32_t n) { (void)p; ++gps_calls; gps_bytes += n; return fail_uart ? -1 : 0; }
const gps_data_t *gps_get_data(void) { return &g; }
fota_state_t fota_get_state(void) { return FOTA_STATE_IDLE; }
bool ec800m_is_ready(void) { return true; }
tcp_state_t ec800m_tcp_state(uint8_t ch) { (void)ch; return TCP_STATE_OPEN; }
int ec800m_tcp_send(uint8_t ch, const uint8_t *p, uint16_t n) { (void)ch; (void)p; (void)n; return 0; }
device_config_t *cfg_get(void) { return &c; }

#include "agnss_huada.c"
#include "agnss_zhongkewei.c"

static void make_huada_zero(uint8_t frame[8]) {
    frame[0] = 0xf1; frame[1] = 0xd9; frame[2] = 0x0b; frame[3] = 0x10;
    frame[4] = 0; frame[5] = 0; frame[6] = 0x1b; frame[7] = 0x5c;
}

static void make_zhongkewei(uint8_t frame[14]) {
    static const uint8_t payload[6] = {'a', 'b', 'c', 'd', 'e', 'f'};
    uint8_t c1 = 0, c2 = 0;
    frame[0] = 'A'; frame[1] = 'G'; frame[2] = 6; frame[3] = 0; frame[4] = 0;
    memcpy(frame + 5, payload, sizeof payload);
    for (unsigned i = 2; i < 11; ++i) { c1 = (uint8_t)(c1 + frame[i]); c2 = (uint8_t)(c2 + c1); }
    frame[11] = c1; frame[12] = c2; frame[13] = 0;
}

int main(void) {
    uint8_t valid[8], oversized[8] = {0xf1, 0xd9, 0x0b, 0x10, 0xff, 0xff, 0, 0};
    make_huada_zero(valid);
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

    { const uint8_t *p; uint16_t n;
      assert(zhongkewei_parse_response((const uint8_t *)"A", 1, &p, &n) == ZK_RESP_INCOMPLETE);
      assert(zhongkewei_parse_response((const uint8_t *)"XX", 2, &p, &n) == ZK_RESP_MALFORMED);
    }
    {
      /* Exercise the production streaming entry point, not only the parser:
       * incomplete data must wait without injecting GPS, and malformed
       * AG-prefixed frames must be rejected and clear the buffered state. */
      uint8_t response[14], bad_checksum[14], bad_length[5];
      make_zhongkewei(response);
      memcpy(bad_checksum, response, sizeof response);
      bad_checksum[11] ^= 0x01;
      bad_length[0] = 'A'; bad_length[1] = 'G';
      bad_length[2] = 2; bad_length[3] = 0; bad_length[4] = 0;

      assert(agnss_zhongkewei_request(
          &(agnss_source_t){response, 4}, &(gps_context_t){0}) == 0);
      assert(gps_calls == 4);

      assert(agnss_zhongkewei_request(
          &(agnss_source_t){bad_checksum, sizeof bad_checksum}, &(gps_context_t){0}) < 0);
      assert(gps_calls == 4);

      assert(agnss_zhongkewei_request(
          &(agnss_source_t){bad_length, sizeof bad_length}, &(gps_context_t){0}) < 0);
      assert(gps_calls == 4);

      /* A valid response must still be accepted after the rejected garbage. */
      assert(agnss_zhongkewei_request(
          &(agnss_source_t){response, sizeof response}, &(gps_context_t){0}) == 0);
      assert(gps_calls == 5);
    }
    { uint8_t response[14]; make_zhongkewei(response);
      fail_uart = 0;
      assert(agnss_zhongkewei_request(&(agnss_source_t){response, 4}, &(gps_context_t){0}) == 0);
      assert(gps_calls == 5);
      fail_uart = 1;
      assert(agnss_zhongkewei_request(&(agnss_source_t){response + 4, 10}, &(gps_context_t){0}) < 0);
      assert(gps_calls == 6);
      fail_uart = 0;
      assert(agnss_zhongkewei_request(&(agnss_source_t){response, sizeof response}, &(gps_context_t){0}) == 0);
      assert(gps_calls == 7);
      assert(gps_bytes == 4 * 8 + 3 * 3);
    }
    return 0;
}
''', encoding="ascii")


def test_c_harness():
    compiler = shutil.which("gcc") or shutil.which("cc")
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
        build = subprocess.run([compiler, "-std=c99", "-I", str(directory), "-I", str(ROOT / "src"), str(directory / "harness.c"), "-o", str(output), "-lm"], cwd=ROOT, capture_output=True, text=True)
        if build.returncode:
            raise AssertionError("C harness compile failed:\n" + build.stderr)
        run = subprocess.run([str(output)], cwd=ROOT, capture_output=True, text=True)
        if run.returncode:
            raise AssertionError("C harness failed (exit %d):\n%s" % (run.returncode, run.stderr))
        print("test_agnss_vendor_stream: C harness PASS")


if __name__ == "__main__":
    test_c_harness()
    print("test_agnss_vendor_stream: PASS")
