"""Host end-to-end harness for +CMT -> FIFO -> F39 -> SMS reply."""

import os
import pathlib
import shutil
import subprocess
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[2]


def compiler():
    found = shutil.which("gcc")
    if found:
        return found
    base = pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    candidates = list(base.glob("BrechtSanders.WinLibs*/mingw64/bin/gcc.exe"))
    candidates += list(pathlib.Path.home().glob("scoop/apps/gcc/current/bin/gcc.exe"))
    if candidates:
        return str(candidates[0])
    if os.environ.get("REQUIRE_GCC") == "1":
        raise RuntimeError("gcc is required but was not found")
    return None


HARNESS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "at_config.h"
#include "f39_reply.h"
#include "gps.h"
#include "sms_command.h"
#include "sms_ingress.h"

static device_config_t config;
static unsigned saves, resets, callbacks;
static char order[16]; static unsigned order_len;
static char sent_to[4][SMS_PHONE_MAX_LEN];
static char sent_text[4][F39_REPLY_MAX_LENGTH]; static unsigned sent_count;
static int send_result;
static void effect(char c);
volatile uint32_t g_tick_ms;
device_config_t *cfg_get(void) { return &config; }
bool cfg_store_candidate(const device_config_t *c) { config = *c; saves++; return true; }
void jt808_set_heartbeat_s(uint16_t s) { (void)s; }
void jt808_set_report_interval(uint16_t a, uint16_t b) { (void)a; (void)b; }
void jt808_set_server(const char *ip, uint16_t p, bool b) { (void)ip; (void)p; (void)b; }
void cfg_save(void) { }
int dbg_printf(const char *fmt, ...) { (void)fmt; return 0; }
void tcp_manager_reconnect(void) { effect('N'); }
void gnss_vendor_set_type(gnss_type_t t) { (void)t; }
void agnss_init(gnss_type_t t) { (void)t; }
int jt808_send_register(void) { effect('J'); return 0; }
void relay_set(bool on) { (void)on; }
bool relay_get(void) { return false; }
bool gps_is_valid(void) { return true; }
const gps_data_t *gps_get_data(void) { static gps_data_t g; g.valid=true; return &g; }
void gps_send_cmd(const char *c) { (void)c; }
void ec800m_get_imei(char *b, uint8_t n) { if (n > 0) { strncpy(b, "123456789012345", n-1); b[n-1]=0; } }
int ec800m_get_csq(void) { return 20; }
void NVIC_SystemReset(void) { }
int sms_send(const char *p, const char *t) { (void)p; (void)t; return 0; }

static void effect(char c) { order[order_len++] = c; order[order_len] = 0; callbacks++; }
static bool persist(const device_config_t *candidate, void *ctx) { (void)candidate; (void)ctx; saves++; return true; }
static void timer(void *ctx) { (void)ctx; effect('T'); }
static void network(void *ctx) { (void)ctx; effect('N'); }
static void gnss(gnss_type_t type, uint8_t mode, void *ctx) { (void)type; (void)mode; (void)ctx; effect('G'); }
static void jt808(void *ctx) { (void)ctx; effect('J'); }
static void remaining(void *ctx) { (void)ctx; effect('R'); }
static bool relay(bool cut, void *ctx) { (void)cut; (void)ctx; callbacks++; return true; }
static bool gps_valid(void *ctx) { (void)ctx; return true; }
static float gps_speed(void *ctx) { (void)ctx; return 0.0f; }
static bool relay_state(void *ctx) { (void)ctx; return false; }
static int send_sms(const char *to, const char *text, void *ctx) {
    (void)ctx;
    if (send_result != 0) return send_result;
    assert(sent_count < 4); strcpy(sent_to[sent_count], to); strcpy(sent_text[sent_count], text); sent_count++;
    return 0;
}
static void schedule_reset(uint32_t delay_ms, void *ctx) { (void)ctx; assert(delay_ms == F39_RESET_DELAY_MS); resets++; }

static void feed(const char *from, const char *body) {
    char header[64]; snprintf(header, sizeof header, "+CMT: \"%s\",\"\"", from);
    sms_ingress_feed_line(header); sms_ingress_feed_line(body);
}

int main(void) {
    f39_platform_t platform;
    memset(&config, 0, sizeof config); config.gnss_type = GNSS_TYPE_TAU804M;
    strcpy(config.terminal_model, "A300_406"); strcpy(config.server_ip, "old");
    memset(&platform, 0, sizeof platform); platform.config=&config; platform.persist=persist;
    platform.timer_refresh=timer; platform.network_reconnect=network; platform.gnss_set_mode=gnss;
    platform.jt808_reregister=jt808; platform.remaining_refresh=remaining; platform.relay_set=relay;
    platform.gps_valid=gps_valid; platform.gps_speed_kmh=gps_speed; platform.relay_get=relay_state;
    platform.version="V3"; platform.version_len=2; platform.imei="123456789012345"; platform.imei_len=15;
    at_config_bind_f39(&platform, send_sms, schedule_reset, 0);
    sms_queue_reset(); sms_ingress_set_callback(at_config_receive_sms);

    feed("13800000001", "IP,one.example,9001#");
    feed("13800000002", "RELAY,0#");
    sms_ingress_process(); sms_ingress_process();
    assert(sent_count == 2 && !strcmp(sent_to[0], "13800000001") && !strcmp(sent_to[1], "13800000002"));
    assert(strstr(sent_text[0], "IP=Success!") && strstr(sent_text[1], "RELAY,0=Success!"));
    assert(saves == 1 && !strcmp(config.server_ip, "one.example") && config.server_port == 9001);

    order_len=0; callbacks=0;
    feed("13800000003", "DUALSET,FREQ,10,20*IP,two.example,9002*GPSBDS,2*MODEL,T360#"); sms_ingress_process();
    assert(!strcmp(order, "TNGJR")); assert(callbacks == 5 && saves == 2);

    callbacks=0; sent_count=0;
    feed("13800000004", "VIBSENS,1#"); sms_ingress_process();
    assert(callbacks == 0 && sent_count == 0);

    send_result=-1; feed("13800000005", "RESET#"); sms_ingress_process();
    assert(resets == 0);
    send_result=0; feed("13800000005", "RESET#"); sms_ingress_process();
    assert(resets == 1 && sent_count == 1 && strstr(sent_text[0], "RESET=Success!"));
    puts("PASS"); return 0;
}
'''


def test_f39_end_to_end():
    cc = compiler()
    if not cc:
        print("SKIP: gcc not found")
        return
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        harness = tmp / "f39_e2e.c"
        exe = tmp / "f39_e2e.exe"
        harness.write_text(HARNESS, encoding="ascii")
        (tmp / "n32l40x.h").write_text("#ifndef N32L40X_H\n#define N32L40X_H\n#include <stdint.h>\ntypedef int BitAction;\n#define ENABLE 1\n#define DISABLE 0\nvoid NVIC_SystemReset(void);\n#endif\n", encoding="ascii")
        cmd = [
            cc, "-std=c99", "-Wall", "-Wextra", "-Werror", "-ffunction-sections",
            "-fdata-sections", "-I", str(tmp), "-I", str(ROOT / "include"), str(harness),
            str(ROOT / "src" / "at_config.c"), str(ROOT / "src" / "sms_command.c"),
            str(ROOT / "src" / "sms_ingress.c"), str(ROOT / "src" / "f39_command.c"),
            str(ROOT / "src" / "f39_config_adapter.c"), str(ROOT / "src" / "f39_reply.c"),
            "-Wl,--gc-sections", "-lm", "-o", str(exe),
        ]
        subprocess.run(cmd, check=True, cwd=ROOT)
        subprocess.run([str(exe)], check=True, cwd=ROOT)


if __name__ == "__main__":
    test_f39_end_to_end()
