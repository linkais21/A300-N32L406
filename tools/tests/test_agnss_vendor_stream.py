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
zhongkewei_resp_t zhongkewei_parse_csip_frame(const uint8_t *, uint32_t, const uint8_t **, uint16_t *);
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

static uint32_t harness_le32(const uint8_t *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static uint32_t csip_checksum(uint8_t cls, uint8_t id, const uint8_t *payload, uint16_t len) {
    uint32_t sum = ((uint32_t)id << 24) + ((uint32_t)cls << 16) + len;
    for (uint16_t i = 0; i < len; i += 4) sum += harness_le32(payload + i);
    return sum;
}

static uint16_t make_csip(uint8_t *frame, uint8_t cls, uint8_t id,
                          const uint8_t *payload, uint16_t len) {
    uint32_t sum;
    frame[0] = 0xba; frame[1] = 0xce;
    frame[2] = (uint8_t)len; frame[3] = (uint8_t)(len >> 8);
    frame[4] = cls; frame[5] = id;
    if (len) memcpy(frame + 6, payload, len);
    sum = csip_checksum(cls, id, payload, len);
    frame[6 + len] = (uint8_t)sum;
    frame[7 + len] = (uint8_t)(sum >> 8);
    frame[8 + len] = (uint8_t)(sum >> 16);
    frame[9 + len] = (uint8_t)(sum >> 24);
    return (uint16_t)(len + 10);
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

    {
      static const uint8_t payload_a[20] = {
          0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19
      };
      static const uint8_t payload_b[16] = {
          0x10, 0, 0, 0, 0x20, 0, 0, 0, 0x30, 0, 0, 0, 0x40, 0, 0, 0
      };
      uint8_t response_a[64], response_b[64], concat[128], bad[64];
      uint16_t n_a = make_csip(response_a, 0x08, 0x00, payload_a, sizeof payload_a);
      uint16_t n_b = make_csip(response_b, 0x08, 0x01, payload_b, sizeof payload_b);
      const uint8_t *parsed; uint16_t parsed_len;

      /* Exact CASBIN checksum and frame shape are independently constructed. */
      assert(zhongkewei_parse_csip_frame(response_a, n_a, &parsed, &parsed_len) == ZK_RESP_OK);
      assert(parsed == response_a && parsed_len == n_a);
      assert(zhongkewei_parse_csip_frame(response_a, n_a - 1, &parsed, &parsed_len) == ZK_RESP_INCOMPLETE);
      assert(zhongkewei_parse_csip_frame((const uint8_t *)"XX", 2, &parsed, &parsed_len) == ZK_RESP_MALFORMED);
      { uint8_t invalid_len[4] = {0xba, 0xce, 0x01, 0x00};
        assert(zhongkewei_parse_csip_frame(invalid_len, sizeof invalid_len, &parsed, &parsed_len) == ZK_RESP_MALFORMED);
      }

      /* Offline injection must not require configured credentials. */
      c.agnss_user[0] = 0; c.agnss_pwd[0] = 0;
      assert(agnss_zhongkewei_request(
          &(agnss_source_t){response_a, 5}, &(gps_context_t){0}) == 0);
      assert(gps_calls == 4);
      assert(agnss_zhongkewei_request(
          &(agnss_source_t){response_a + 5, n_a - 5}, &(gps_context_t){0}) == 0);
      assert(gps_calls == 5);
      assert(gps_bytes == 4 * 8 + n_a);

      /* Leading garbage resynchronizes; concatenated complete frames forward once each. */
      concat[0] = 0x11; concat[1] = 0xba; concat[2] = 0x55;
      memcpy(concat + 3, response_a, n_a); memcpy(concat + 3 + n_a, response_b, n_b);
      assert(agnss_zhongkewei_request(&(agnss_source_t){concat, (uint32_t)(3 + n_a + n_b)}, &(gps_context_t){0}) == 0);
      assert(gps_calls == 7);

      /* Checksum, non-MSG, and wrong ID/length must fail closed and reset. */
      memcpy(bad, response_a, n_a); bad[n_a - 1] ^= 1;
      assert(agnss_zhongkewei_request(&(agnss_source_t){bad, n_a}, &(gps_context_t){0}) < 0);
      assert(agnss_zhongkewei_request(&(agnss_source_t){response_a, n_a}, &(gps_context_t){0}) == 0);
      assert(gps_calls == 8);
      make_csip(bad, 0x06, 0x00, payload_a, sizeof payload_a);
      assert(agnss_zhongkewei_request(&(agnss_source_t){bad, n_a}, &(gps_context_t){0}) < 0);
      make_csip(bad, 0x08, 0x02, payload_b, sizeof payload_b);
      assert(agnss_zhongkewei_request(&(agnss_source_t){bad, n_b}, &(gps_context_t){0}) < 0);
      make_csip(bad, 0x08, 0x00, payload_b, sizeof payload_b);
      assert(agnss_zhongkewei_request(&(agnss_source_t){bad, n_b}, &(gps_context_t){0}) < 0);
    }
    { static const uint8_t payload[20] = {0}; uint8_t response[64]; uint16_t n = make_csip(response, 0x08, 0x00, payload, sizeof payload);
      fail_uart = 0;
      assert(agnss_zhongkewei_request(&(agnss_source_t){response, 4}, &(gps_context_t){0}) == 0);
      assert(gps_calls == 8);
      fail_uart = 1;
      assert(agnss_zhongkewei_request(&(agnss_source_t){response + 4, n - 4}, &(gps_context_t){0}) < 0);
      assert(gps_calls == 9);
      fail_uart = 0;
      assert(agnss_zhongkewei_request(&(agnss_source_t){response, n}, &(gps_context_t){0}) == 0);
      assert(gps_calls == 10);
    }
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
