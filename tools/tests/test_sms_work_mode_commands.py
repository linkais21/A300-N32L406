"""Contract test for SMS timer synchronization and bounded status queries."""

import os
import pathlib
import shutil
import subprocess
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[2]


def compiler():
    cc = shutil.which("gcc")
    if cc:
        return cc
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
#include "f39_command.h"
#include "f39_config_adapter.h"
#include "f39_reply.h"
#include "gps.h"

static device_config_t cfg;
static unsigned saves;
static unsigned timer_refreshes;
static char reply_text[F39_REPLY_MAX_LENGTH];

device_config_t *cfg_get(void) { return &cfg; }
bool cfg_store_candidate(const device_config_t *c) { cfg = *c; ++saves; return true; }
cfg_store_result_t cfg_set_pid_result(const char pid[CFG_PID_LEN]) { (void)pid; return CFG_STORE_OK; }
void jt808_set_heartbeat_s(uint16_t s) { (void)s; }
void jt808_set_report_interval(uint16_t moving, uint16_t stopped) { (void)moving; (void)stopped; }
void work_mode_config_changed(const device_config_t *c, uint32_t now) { (void)c; (void)now; ++timer_refreshes; }
int dbg_printf(const char *fmt, ...) { (void)fmt; return 0; }
int sms_send(const char *to, const char *text) { (void)to; strncpy(reply_text, text, sizeof reply_text - 1U); return 0; }
void sms_set_send_result_cb(void (*cb)(bool)) { (void)cb; }
int GPIO_ReadInputDataBit(void *p, unsigned pin) { (void)p; (void)pin; return 1; }
void ec800m_get_imei(char *out, uint8_t cap) { if (cap) { strncpy(out, "123456789012345", cap - 1U); out[cap - 1U] = 0; } }
int ec800m_get_csq(void) { return 20; }
const gps_data_t *gps_get_data(void) { static gps_data_t g; g.valid = true; g.fix_quality = 1; return &g; }
bool gps_is_valid(void) { return true; }
void gps_send_cmd(const char *cmd) { (void)cmd; }
void gnss_vendor_set_type(gnss_type_t type) { (void)type; }
void agnss_init(gnss_type_t type) { (void)type; }
void jt808_set_server(const char *ip, uint16_t port, bool backup) { (void)ip; (void)port; (void)backup; }
void tcp_manager_reconnect(void) {}
void jt808_request_reregister(void) {}
void relay_set(bool cut) { (void)cut; }
bool relay_get(void) { return false; }
void NVIC_SystemReset(void) {}
volatile uint32_t g_tick_ms;

static bool persist(const device_config_t *candidate, void *ctx) { (void)ctx; cfg = *candidate; ++saves; return true; }
static void timer(void *ctx) { (void)ctx; ++timer_refreshes; }
static int send_reply(const char *to, const char *text, void *ctx) { (void)to; (void)ctx; strncpy(reply_text, text, sizeof reply_text - 1U); return 0; }
static void reset_schedule(uint32_t delay, void *ctx) { (void)delay; (void)ctx; }

int main(void) {
    f39_platform_t platform;
    f39_request_t request;
    f39_reply_t reply;
    f39_transaction_t tx;
    memset(&cfg, 0, sizeof cfg);
    cfg.gnss_type = GNSS_TYPE_TAU804M;
    strcpy(cfg.terminal_model, "A300_406");
    strcpy(cfg.server_ip, "host");
    strcpy(cfg.backup_ip, "backup");
    strcpy(cfg.apn, "cmnet");
    cfg.report_moving_s = 30; cfg.report_stopped_s = 180; cfg.heartbeat_s = 180;
    memset(&platform, 0, sizeof platform);
    platform.config = &cfg; platform.persist = persist; platform.timer_refresh = timer;
    platform.version = "V1"; platform.version_len = 2;
    platform.imei = "123456789012345"; platform.imei_len = 15;
    platform.iccid = "89860492192080502719"; platform.iccid_len = 20;
    assert(f39_parse((const uint8_t *)"FREQ,30,180", 11, &request) == F39_RESULT_OK);
    f39_transaction_init(&tx, &cfg, persist, 0);
    assert(f39_prepare_config(&request, &cfg, &tx));
    assert(f39_commit_config(&tx) == F39_RESULT_OK);
    assert(cfg.report_moving_s == 30 && cfg.report_stopped_s == 180 && saves == 1);
    assert(f39_parse((const uint8_t *)"HBT,180", 7, &request) == F39_RESULT_OK);
    f39_transaction_init(&tx, &cfg, persist, 0);
    assert(f39_prepare_config(&request, &cfg, &tx));
    assert((tx.effects & F39_EFFECT_TIMER_REFRESH) != 0U);
    assert(f39_commit_config(&tx) == F39_RESULT_OK);
    assert(f39_execute(&(f39_request_t){0}, &platform, &reply) == F39_RESULT_INVALID);
    assert(f39_parse((const uint8_t *)"PARAM?", 6, &request) == F39_RESULT_OK);
    assert(f39_execute(&request, &platform, &reply) == F39_RESULT_OK);
    assert(reply.len < F39_REPLY_MAX_LENGTH);
    /* Terminal command spec sheet1 row 3: bracketed PARAM format. */
    assert(strstr((const char *)reply.data, "PRO[JT808_2013]") != 0);
    assert(strstr((const char *)reply.data, "IMEI[123456789012345]") != 0);
    assert(strstr((const char *)reply.data, "ICCID[89860492192080502719]") != 0);
    assert(strstr((const char *)reply.data, "FORCE[30:180]") != 0);
    assert(f39_parse((const uint8_t *)"FOTA?", 5, &request) == F39_RESULT_OK);
    assert(f39_execute(&request, &platform, &reply) == F39_RESULT_OK);
    assert(reply.len < F39_REPLY_MAX_LENGTH && strstr((const char *)reply.data, "FOTA,") != 0);
    assert(f39_parse((const uint8_t *)"LOG?", 4, &request) == F39_RESULT_OK);
    assert(f39_execute(&request, &platform, &reply) == F39_RESULT_OK);
    assert(reply.len < F39_REPLY_MAX_LENGTH && strstr((const char *)reply.data, "LOG,") != 0);
    (void)timer_refreshes;
    (void)send_reply; (void)reset_schedule; (void)at_config_init;
    puts("sms work-mode command contract: PASS");
    return 0;
}
'''


def test_sms_work_mode_commands():
    cc = compiler()
    if not cc:
        print("SKIP: gcc not found")
        return
    with tempfile.TemporaryDirectory() as directory:
        directory = pathlib.Path(directory)
        source = directory / "sms_commands.c"
        executable = directory / "sms_commands.exe"
        source.write_text(HARNESS, encoding="ascii")
        command = [
            cc, "-std=c99", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "include"),
            str(source), str(ROOT / "src" / "f39_command.c"),
            str(ROOT / "src" / "f39_config_adapter.c"), str(ROOT / "src" / "f39_reply.c"),
            str(ROOT / "src" / "terminal_identity.c"), "-lm", "-o", str(executable),
        ]
        subprocess.run(command, check=True, cwd=ROOT)
        subprocess.run([str(executable)], check=True, cwd=ROOT)


if __name__ == "__main__":
    test_sms_work_mode_commands()
