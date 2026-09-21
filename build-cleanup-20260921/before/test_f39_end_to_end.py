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
#include "peripherals.h"

static device_config_t config;
static unsigned saves, resets, callbacks;
static char order[16]; static unsigned order_len;
static char sent_to[4][SMS_PHONE_MAX_LEN];
static char sent_text[4][F39_REPLY_MAX_LENGTH]; static unsigned sent_count;
static int send_result;
static sms_send_result_cb_t production_result_cb;
static unsigned production_sends, system_resets;
static int production_send_result;
static void effect(char c);
volatile uint32_t g_tick_ms;
device_config_t *cfg_get(void) { return &config; }
bool cfg_store_candidate(const device_config_t *c) { config = *c; saves++; return true; }
cfg_store_result_t cfg_set_pid_result(const char pid[CFG_PID_LEN])
{ memcpy(config.pid, pid, CFG_PID_LEN); return CFG_STORE_OK; }
void jt808_set_heartbeat_s(uint16_t s) { (void)s; }
void jt808_set_report_interval(uint16_t a, uint16_t b) { (void)a; (void)b; }
void jt808_set_server(const char *ip, uint16_t p, bool b) { (void)ip; (void)p; (void)b; }
void cfg_save(void) { }
int dbg_printf(const char *fmt, ...) { (void)fmt; return 0; }
void tcp_manager_reconnect(void) { effect('N'); }
bool fota_request_check(void) { return true; }
void gnss_vendor_set_type(gnss_type_t t) { (void)t; }
void agnss_init(gnss_type_t t) { (void)t; }
void jt808_request_reregister(void) { effect('J'); }
void jt808_set_terminal_profile(const char *model, const char *plate) { (void)model; (void)plate; }
void jt808_reset_endpoint_auth(uint8_t mask) { (void)mask; }
uint32_t work_mode_sleep_monotonic_s(void) { return g_tick_ms / 1000U; }
void relay_set(bool on) { (void)on; }
uint16_t relay_test_remaining(void) { return 0U; }
bool production_test_command(const char *line) { (void)line; return false; }
bool relay_get(void) { return false; }
bool gps_quality_fix_fresh(void) { return false; }
bool gps_get_quality(gps_quality_t *q) { memset(q, 0, sizeof(*q)); return false; }
bool gps_is_valid(void) { return true; }
const gps_data_t *gps_get_data(void) { static gps_data_t g; g.valid=true; return &g; }
void gps_send_cmd(const char *c) { (void)c; }
int GPIO_ReadInputDataBit(void *p, unsigned x) { (void)p; (void)x; return 1; }
bool hw_acc_is_on(void) { return true; }
void ec800m_get_imei(char *b, uint8_t n) { if (n > 0) { strncpy(b, "123456789012345", n-1); b[n-1]=0; } }
void ec800m_get_iccid(char *b, uint8_t n) { if (n > 0) { strncpy(b, "89860492192080502719", n-1); b[n-1]=0; } }
int ec800m_get_csq(void) { return 20; }
void ec800m_restart_pdp(void) { effect('P'); }
void NVIC_SystemReset(void) { system_resets++; }
int sms_send(const char *p, const char *t) { (void)p; (void)t; production_sends++; return production_send_result; }
void sms_set_send_result_cb(sms_send_result_cb_t cb) { production_result_cb=cb; }

static void effect(char c) { order[order_len++] = c; order[order_len] = 0; callbacks++; }
static bool persist(const device_config_t *candidate, void *ctx) { (void)candidate; (void)ctx; saves++; return true; }
static void timer(void *ctx) { (void)ctx; effect('T'); }
static void network(void *ctx) { (void)ctx; effect('N'); }
static void auth_reset(uint8_t mask, void *ctx) { (void)mask; (void)ctx; effect('A'); }
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
    platform.jt808_auth_reset=auth_reset;
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
    assert(!strcmp(order, "TANGJR")); assert(callbacks == 6 && saves == 2);

    callbacks=0; sent_count=0;
    feed("13800000004", "VIBSENSX,1#"); sms_ingress_process();
    assert(callbacks == 0 && sent_count == 0);

    send_result=-1; feed("13800000005", "RESET#"); sms_ingress_process();
    assert(resets == 0);
    send_result=0; feed("13800000005", "RESET#"); sms_ingress_process();
    assert(resets == 1 && sent_count == 1 && strstr(sent_text[0], "RESET=Success!"));

    at_config_bind_f39(0, 0, 0, 0); at_config_init();
    production_send_result=-2;
    assert(at_config_execute_sms("13800000006",(const uint8_t*)"PARAM",5));
    assert(production_sends==1 && production_result_cb);
    production_send_result=0; g_tick_ms=1000U; at_config_process();
    assert(production_sends==2);
    production_result_cb(true);
    at_config_process();
    assert(production_sends==2);
    assert(at_config_execute_sms("13800000006",(const uint8_t*)"RESET",5));
    assert(system_resets==0); production_result_cb(false); assert(system_resets==0);
    assert(!at_config_execute_sms("13800000007",(const uint8_t*)"PARAM",5));
    g_tick_ms+=1000U; at_config_process();
    assert(production_sends==4);
    production_result_cb(true); g_tick_ms+=F39_RESET_DELAY_MS; at_config_process(); assert(system_resets==1);
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
        (tmp / "n32l40x.h").write_text("#ifndef N32L40X_H\n#define N32L40X_H\n#include <stdint.h>\ntypedef int BitAction;\n#define ENABLE 1\n#define DISABLE 0\n#define Bit_RESET 0\n#define GPIOA ((void*)0)\n#define GPIO_PIN_3 3\n#define GPIO_PIN_12 12\nint GPIO_ReadInputDataBit(void*,unsigned);\nvoid NVIC_SystemReset(void);\n#endif\n", encoding="ascii")
        cmd = [
            cc, "-std=c99", "-Wall", "-Wextra", "-Werror", "-ffunction-sections",
            "-fdata-sections", "-I", str(tmp), "-I", str(ROOT / "include"), str(harness),
            str(ROOT / "src" / "at_config.c"), str(ROOT / "src" / "sms_command.c"),
            str(ROOT / "src" / "sms_ingress.c"), str(ROOT / "src" / "f39_command.c"),
            str(ROOT / "src/plate_encoding.c"), str(ROOT / "src" / "f39_config_adapter.c"), str(ROOT / "src" / "f39_reply.c"),
            str(ROOT / "src" / "terminal_identity.c"),
            "-Wl,--gc-sections", "-lm", "-o", str(exe),
        ]
        subprocess.run(cmd, check=True, cwd=ROOT)
        subprocess.run([str(exe)], check=True, cwd=ROOT)


PRODUCTION_HARNESS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "at_config.h"
#include "config.h"
#include "ec800m.h"
#include "f39_reply.h"
#include "gps.h"
#include "peripherals.h"
#include "sms_ingress.h"

volatile uint32_t g_tick_ms;
static device_config_t config;
static unsigned saves, reset_scheduled, system_resets;
static unsigned cfg_saves, timer_calls, network_calls, gnss_calls;
static unsigned jt808_register_calls, relay_calls, relay_state;
static unsigned jt808_profile_calls;
static char runtime_model[CFG_MODEL_LEN];
static char runtime_plate[CFG_PLATE_LEN];
static char backup_endpoint[CFG_IP_LEN];
static uint16_t backup_endpoint_port;
unsigned inject_cmt_during_tcp_wait;
static unsigned gps_cmd_calls;
char tx_log[4096];
unsigned tx_len;
unsigned modem_write_phase;
int race_sms_result;
int tx_stuck;
unsigned pdp_auto_reply;

void ec800m_test_set_state(ec800m_state_t state);
void ec800m_test_set_imei(const char *imei);
void ec800m_test_set_iccid(const char *iccid);
void ec800m_test_set_tcp_open(uint8_t ch);
void ec800m_restart_pdp(void);

/* The modem shim writes every UART5 byte into tx_log and advances the DMA
 * producer.  Responses are injected by the harness after each process step. */
void host_uart_tx(uint8_t b);
void host_feed_rx(const char *s);

device_config_t *cfg_get(void) { return &config; }
bool cfg_store_candidate(const device_config_t *c) { config = *c; ++saves; ++cfg_saves; return true; }
cfg_store_result_t cfg_set_pid_result(const char pid[CFG_PID_LEN])
{ memcpy(config.pid, pid, CFG_PID_LEN); return CFG_STORE_OK; }
void cfg_save(void) { ++saves; }
void jt808_set_heartbeat_s(uint16_t s) { (void)s; ++timer_calls; }
void jt808_set_report_interval(uint16_t a, uint16_t b) { (void)a; (void)b; ++timer_calls; }
void jt808_set_server(const char *ip, uint16_t p, bool backup) { if (backup) { strncpy(backup_endpoint, ip, sizeof(backup_endpoint) - 1U); backup_endpoint[sizeof(backup_endpoint) - 1U] = '\0'; backup_endpoint_port = p; } ++network_calls; }
void tcp_manager_reconnect(void) { ++network_calls; }
bool fota_request_check(void) { return true; }
void gnss_vendor_set_type(gnss_type_t t) { (void)t; ++gnss_calls; }
void agnss_init(gnss_type_t t) { (void)t; ++gnss_calls; }
void jt808_request_reregister(void) { ++jt808_register_calls; }
void jt808_reset_endpoint_auth(uint8_t mask) { (void)mask; }
uint32_t work_mode_sleep_monotonic_s(void) { return g_tick_ms / 1000U; }
void jt808_set_terminal_profile(const char *model, const char *plate) {
    ++jt808_profile_calls;
    strncpy(runtime_model, model, sizeof runtime_model - 1U);
    strncpy(runtime_plate, plate, sizeof runtime_plate - 1U);
}
void relay_set(bool on) { relay_state = on ? 1U : 0U; ++relay_calls; }
uint16_t relay_test_remaining(void) { return 0U; }
bool production_test_command(const char *line) { (void)line; return false; }
bool relay_get(void) { return relay_state != 0U; }
bool gps_quality_fix_fresh(void) { return false; }
bool gps_get_quality(gps_quality_t *q) { memset(q, 0, sizeof(*q)); return false; }
bool gps_is_valid(void) { return true; }
const gps_data_t *gps_get_data(void) { static gps_data_t g = { .valid = true, .fix_quality = 4, .satellites = 12, .hdop = 0.8f, .speed_kmh = 0.0f }; return &g; }
void gps_send_cmd(const char *c) { (void)c; ++gps_cmd_calls; }
int dbg_printf(const char *fmt, ...) { (void)fmt; return 0; }
void NVIC_SystemReset(void) { ++system_resets; }
void delay_ms(uint32_t ms) { g_tick_ms += ms; }
void delay_us(uint32_t us) { (void)us; }
void GPIO_SetBits(void *p, unsigned pin) { (void)p; (void)pin; }
void GPIO_ResetBits(void *p, unsigned pin) { (void)p; (void)pin; }
int GPIO_ReadInputDataBit(void *p, unsigned pin) { (void)p; (void)pin; return 1; }
bool hw_acc_is_on(void) { return true; }

static void sms_dispatch(const char *from, const char *text) {
    uint16_t n = (uint16_t)strlen(text);
    (void)at_config_execute_sms(from, (const uint8_t *)text, n);
}
static bool persist(const device_config_t *c, void *ctx) { (void)ctx; config = *c; ++saves; return true; }
static void reset_schedule(uint32_t delay, void *ctx) { (void)ctx; assert(delay == F39_RESET_DELAY_MS); ++reset_scheduled; }

static void feed_cmt(const char *from, const char *body) {
    char line[64];
    snprintf(line, sizeof line, "+CMT: \"%s\",\"\",\"\"", from);
    host_feed_rx(line); host_feed_rx("\r\n"); host_feed_rx(body); host_feed_rx("\r\n");
}
static void modem_step(void) { ec800m_process(); }
static void complete_sms(bool ok) {
    host_feed_rx(">\r\n"); modem_step();
    if (ok) host_feed_rx("\r\n+CMGS: 1\r\n");
    else host_feed_rx("\r\nERROR\r\n");
    modem_step();
}

int main(void) {
    f39_platform_t platform;
    memset(&config, 0, sizeof config);
    config.gnss_type = GNSS_TYPE_TAU804M;
    ec800m_test_set_state(EC800M_STATE_READY);
    ec800m_test_set_imei("123456789012345");
    ec800m_test_set_iccid("89860492192080502719");
    sms_set_recv_cb(sms_dispatch);
    memset(&platform, 0, sizeof platform);
    platform.config = &config; platform.persist = persist;
    platform.version = "V3"; platform.version_len = 2;
    platform.imei = "123456789012345"; platform.imei_len = 15;
    platform.gps_valid = 0; platform.gps_speed_kmh = 0; platform.relay_get = 0;
    at_config_bind_f39(&platform, NULL, reset_schedule, NULL);
    /* NULL send is invalid, so defaults are used by at_config_init(). */
    at_config_bind_f39(NULL, NULL, NULL, NULL);
    at_config_init();

    /* A runtime APN change rebuilds context 1 before data traffic resumes. */
    config.autoapn_en = 0U;
    strcpy(config.apn, "iot.apn");
    strcpy(config.apn_user, "user");
    strcpy(config.apn_pass, "password");
    tx_len = 0U; tx_log[0] = '\0'; pdp_auto_reply = 1U;
    ec800m_restart_pdp(); modem_step();
    assert(ec800m_get_state() == EC800M_STATE_READY);
    {
        const char *deact = strstr(tx_log, "AT+QIDEACT=1");
        const char *profile = strstr(tx_log, "AT+QICSGP=1,1,\"iot.apn\",\"user\",\"password\",1");
        const char *activate = strstr(tx_log, "AT+QIACT=1");
        const char *query = strstr(tx_log, "AT+QIACT?");
        assert(deact && profile && activate && query);
        assert(deact < profile && profile < activate && activate < query);
    }
    config.apn_user[0] = '\0'; config.apn_pass[0] = '\0';
    tx_len = 0U; tx_log[0] = '\0';
    ec800m_restart_pdp(); modem_step();
    assert(ec800m_get_state() == EC800M_STATE_READY);
    assert(strstr(tx_log, "AT+QICSGP=1,1,\"iot.apn\",\"\",\"\",0") != NULL);
    config.autoapn_en = 1U;
    tx_len = 0U; tx_log[0] = '\0';
    ec800m_restart_pdp(); modem_step();
    assert(ec800m_get_state() == EC800M_STATE_READY);
    assert(strstr(tx_log, "AT+QICSGP=1,1,\"\",\"\",\"\",0") != NULL);
    /* Exact field command, through the real F39/default/PDP/UART chain. */
    tx_len = 0U; tx_log[0] = '\0';
    assert(at_config_execute_text_command((const uint8_t *)"APN,cmiot,,", 11U));
    modem_step();
    assert(ec800m_get_state() == EC800M_STATE_READY && config.autoapn_en == 0U);
    assert(!strcmp(config.apn, "cmiot"));
    assert(strstr(tx_log, "AT+QICSGP=1,1,\"cmiot\",\"\",\"\",0") != NULL);
    pdp_auto_reply = 0U;

    /* Exercise the real A300_406 default callback chain. */
    feed_cmt("13900000001", "IP,default.example,9001#");
    modem_step(); sms_process(); modem_step(); complete_sms(true);
    assert(!strcmp(config.server_ip, "default.example") && config.server_port == 9001);
    assert(cfg_saves > 0 && network_calls >= 2);
    feed_cmt("13900000001", "FIP,58.61.154.237,7018#");
    modem_step(); sms_process(); modem_step(); complete_sms(true);
    assert(!strcmp(config.backup_ip, "58.61.154.237") && config.backup_port == 7018U);
    assert(!strcmp(backup_endpoint, "58.61.154.237") && backup_endpoint_port == 7018U);
    feed_cmt("13900000001", "FIP,0#");
    modem_step(); sms_process(); modem_step(); complete_sms(true);
    assert(config.backup_ip[0] == '\0' && config.backup_port == 0U);
    assert(backup_endpoint[0] == '\0' && backup_endpoint_port == 0U);
    feed_cmt("13900000001", "FREQ,10,20#");
    modem_step(); sms_process(); modem_step(); complete_sms(true);
    assert(config.report_moving_s == 10 && config.report_stopped_s == 20 && timer_calls > 0);
    feed_cmt("13900000001", "GPSBDS,2#");
    modem_step(); sms_process(); modem_step(); complete_sms(true);
    assert(config.gpsbds_mode == 2 && gps_cmd_calls > 0 && gnss_calls > 0);
    feed_cmt("13900000001", "PID,76543210987#");
    modem_step(); sms_process(); modem_step(); complete_sms(true);
    assert(!strcmp(config.pid, "76543210987") && jt808_register_calls > 0);
    feed_cmt("13900000001", "MODEL,T360-A300#");
    modem_step(); sms_process(); modem_step(); complete_sms(true);
    assert(!strcmp(runtime_model, "T360-A300") && jt808_profile_calls > 0);
    feed_cmt("13900000001", "CAR,18B12345#");
    modem_step(); sms_process(); modem_step(); complete_sms(true);
    assert(runtime_plate[0] != '\0' && jt808_profile_calls > 1U);
    feed_cmt("13900000001", "RELAY,1#");
    modem_step(); sms_process(); modem_step(); complete_sms(true);
    assert(relay_state == 1 && relay_calls > 0);
    tx_len = 0U; tx_log[0] = '\0';
    feed_cmt("13900000001", "PARAM#");
    modem_step(); sms_process(); modem_step(); complete_sms(true);
    complete_sms(true);
    assert(strstr(tx_log, "ACC[1]") != NULL && strstr(tx_log, "GPS[12]") != NULL);

    /* Two senders traverse the real DMA -> +CMT -> ingress FIFO path. */
    feed_cmt("13800000001", "PARAM#");
    feed_cmt("13800000002", "PARAM#");
    modem_step(); sms_process(); modem_step();
    assert(strstr(tx_log, "AT+QCMGS=\"13800000001\"") != NULL);
    complete_sms(true); complete_sms(true);
    sms_process(); modem_step();
    assert(strstr(tx_log, "AT+QCMGS=\"13800000002\"") != NULL);
    complete_sms(true); complete_sms(true);

    /* Plain ERROR while waiting for the prompt must fail immediately. */
    assert(ec800m_sms_send("13800000003", "X") == 0);
    modem_step();
    host_feed_rx("\r\nERROR\r\n"); modem_step();
    assert(ec800m_sms_send("13800000003", "Y") == 0);
    modem_step(); complete_sms(true);

    /* A failed RESET reply must not leave stale reset handoff state. */
    feed_cmt("13800000004", "RESET#");
    modem_step(); sms_process(); modem_step(); complete_sms(false);
    ec800m_test_set_state(EC800M_STATE_OFF);
    for (unsigned i = 0; i < 3; ++i) { g_tick_ms += 1000; at_config_process(); }
    ec800m_test_set_state(EC800M_STATE_READY);
    assert(ec800m_sms_send("13800000005", "X") == 0);
    modem_step(); complete_sms(true);
    g_tick_ms += F39_RESET_DELAY_MS;
    at_config_process();
    assert(reset_scheduled == 0 && system_resets == 0);

    /* TCP payload and CMGS share one owner: the injected race is rejected. */
    ec800m_test_set_tcp_open(0);
    race_sms_result = -99;
    modem_write_phase = 1;
    assert(ec800m_tcp_send(0, (const uint8_t *)"abc", 3) == 0);
    assert(race_sms_result == -2);

    /* A stuck UART advances the tick through watchdog reloads and returns. */
    tx_stuck = 1;
    assert(ec800m_sms_send("13800000006", "X") == 0);
    modem_step();
    tx_stuck = 0;
    assert(ec800m_sms_send("13800000006", "Y") == 0);
    modem_step(); complete_sms(true);
    /* RESET A failure + ordinary B success must not let B consume A's reset. */
    tx_len = 0; tx_log[0] = '\0';
    feed_cmt("13900000002", "RESET#");
    modem_step(); sms_process(); modem_step(); complete_sms(false);
    feed_cmt("13900000003", "PARAM#");
    modem_step(); sms_process(); modem_step();
    assert(system_resets == 0);
    assert(strstr(tx_log, "AT+CMGS=\"13900000003\"") == NULL);
    g_tick_ms += 1000; at_config_process(); modem_step(); complete_sms(true);
    assert(strstr(tx_log, "AT+CMGS=\"13900000002\"") != NULL);
    g_tick_ms += F39_RESET_DELAY_MS; at_config_process();
    assert(system_resets == 1);

    /* A stale +CMGS from the failed attempt must not complete the retry
     * while it is still waiting for the new prompt. */
    {
        unsigned reset_before = system_resets;
        feed_cmt("13900000006", "RESET#");
        modem_step(); sms_process(); modem_step(); complete_sms(false);
        g_tick_ms += 1000U; at_config_process(); modem_step();
        host_feed_rx("\r\n+CMGS: 77\r\n"); modem_step();
        g_tick_ms += F39_RESET_DELAY_MS; at_config_process();
        assert(system_resets == reset_before);
        complete_sms(true);
        g_tick_ms += F39_RESET_DELAY_MS; at_config_process();
        assert(system_resets == reset_before + 1U);
    }

    /* A CMT arriving during a blocking TCP wait must survive into FIFO. */
    tx_len = 0; tx_log[0] = '\0';
    inject_cmt_during_tcp_wait = 1;
    ec800m_test_set_tcp_open(0);
    assert(ec800m_tcp_send(0, (const uint8_t *)"abc", 3) == 0);
    sms_process(); modem_step();
    assert(strstr(tx_log, "AT+QCMGS=\"13900000004\"") != NULL);
    complete_sms(true);

    puts("PASS"); return 0;
}
'''


def test_f39_production_chain():
    modem_source = (ROOT / "src" / "ec800m.c").read_text(encoding="utf-8")
    assert '>> AT+QICSGP=1,1,<redacted>' in modem_source
    cc = compiler()
    if not cc:
        print("SKIP: gcc not found")
        return
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        (tmp / "harness.c").write_text(PRODUCTION_HARNESS, encoding="ascii")
        (tmp / "n32l40x.h").write_text(r'''
#ifndef N32L40X_H
#define N32L40X_H
#include <stdint.h>
typedef struct { uint32_t DAT; } usart_t;
typedef struct { uint32_t DUMMY; } dma_t;
extern usart_t host_uart5;
#define UART5 (&host_uart5)
#define USART1 (&host_uart5)
#define UART4 (&host_uart5)
#define DMA2 ((dma_t *)0)
#define DMA_CH5 ((dma_t *)5)
#define DMA DMA2
#define DMA_FLAG_HT5 0x01
#define DMA_FLAG_TC5 0x02
#define USART_FLAG_TXDE 0x01
#define USART_FLAG_TXC 0x02
#define USART_FLAG_RXDNE 0x04
#define RESET 0
#define SET 1
#define ENABLE 1
#define DISABLE 0
#define Bit_RESET 0
#define GPIOA ((void *)0)
#define GPIOB ((void *)1)
#define GPIOD ((void *)2)
#define GPIO_PIN_0 0
#define GPIO_PIN_1 1
#define GPIO_PIN_3 3
#define GPIO_PIN_4 4
#define GPIO_PIN_5 5
#define GPIO_PIN_6 6
#define GPIO_PIN_7 7
#define GPIO_PIN_8 8
#define GPIO_PIN_9 9
#define GPIO_PIN_10 10
#define GPIO_PIN_11 11
#define GPIO_PIN_12 12
#define GPIO_PIN_15 15
#define RCC_APB2_PERIPH_UART5 0
#define RCC_APB2_PERIPH_UART4 0
#define RCC_APB2_PERIPH_USART1 0
#define RCC_APB1_PERIPH_I2C1 0
#define RCC_APB2_PERIPH_SPI1 0
#define ADC_CH_1 1
#define ADC_CH_2 2
typedef int BitAction;
uint32_t DMA_GetCurrDataCounter(dma_t *d);
int DMA_GetFlagStatus(uint32_t f, dma_t *d);
void DMA_ClearFlag(uint32_t f, dma_t *d);
int USART_GetFlagStatus(usart_t *u, uint32_t f);
void USART_SendData(usart_t *u, uint8_t b);
uint8_t USART_ReceiveData(usart_t *u);
void IWDG_ReloadKey(void);
void GPIO_SetBits(void *p, unsigned pin);
void GPIO_ResetBits(void *p, unsigned pin);
int GPIO_ReadInputDataBit(void *p, unsigned pin);
void NVIC_SystemReset(void);
#endif
''', encoding="ascii")
        (tmp / "stub.c").write_text(r'''
#include <stdint.h>
#include <string.h>
#include "n32l40x.h"
#include "config.h"
usart_t host_uart5;
static uint16_t wr;
extern uint8_t EC800M_RX_BUF[EC800M_RX_BUF_SIZE];
extern volatile uint32_t g_tick_ms;
extern int race_sms_result;
extern unsigned modem_write_phase;
extern char tx_log[4096];
extern unsigned tx_len;
extern int tx_stuck;
extern unsigned pdp_auto_reply;
extern unsigned inject_cmt_during_tcp_wait;
extern int ec800m_sms_send(const char *, const char *);
void host_feed_rx(const char *s);
void host_uart_tx(uint8_t b) {
    static char at_line[256];
    static unsigned at_line_len;
    if (tx_len + 1 < 4096U) { tx_log[tx_len++] = (char)b; tx_log[tx_len] = '\0'; }
    if (at_line_len + 1U < sizeof at_line) at_line[at_line_len++] = (char)b;
    if (b == '\n') {
        at_line[at_line_len] = '\0';
        if (pdp_auto_reply != 0U) {
            if (strstr(at_line, "AT+QIACT?"))
                host_feed_rx("\r\n+QIACT: 1,1,1,\"10.0.0.1\"\r\nOK\r\n");
            else if (strstr(at_line, "AT+QIDEACT=1") ||
                     strstr(at_line, "AT+QICSGP=1,1") ||
                     strstr(at_line, "AT+QIACT=1"))
                host_feed_rx("\r\nOK\r\n");
        }
        at_line_len = 0U;
    }
    if (inject_cmt_during_tcp_wait == 1U && b == '\n') {
        host_feed_rx(">\r\n+CMT: \"13900000004\",\"\",\"\"\r\nPARAM#\r\n");
        inject_cmt_during_tcp_wait = 2U;
    } else if (inject_cmt_during_tcp_wait == 2U && b == 'c') {
        host_feed_rx("\r\nSEND OK\r\n");
        inject_cmt_during_tcp_wait = 3U;
    }
    if (modem_write_phase == 1 && strstr(tx_log, "AT+QISEND=0,3\r\n") != 0) {
        host_feed_rx(">\r\n");
        modem_write_phase = 2;
    }
    if (modem_write_phase == 2 && b == 'a') {
        race_sms_result = ec800m_sms_send("1", "RACE");
        modem_write_phase = 3;
    } else if (modem_write_phase == 3 && b == 'c') {
        host_feed_rx("\r\nSEND OK\r\n");
        modem_write_phase = 4;
    }
}
void host_feed_rx(const char *s) {
    size_t n = strlen(s);
    for (size_t i = 0; i < n; ++i) { EC800M_RX_BUF[wr++] = (uint8_t)s[i]; if (wr == EC800M_RX_BUF_SIZE) wr = 0; }
}
uint32_t DMA_GetCurrDataCounter(dma_t *d) { (void)d; return (uint32_t)(EC800M_RX_BUF_SIZE - wr); }
int DMA_GetFlagStatus(uint32_t f, dma_t *d) { (void)f; (void)d; return RESET; }
void DMA_ClearFlag(uint32_t f, dma_t *d) { (void)f; (void)d; }
int USART_GetFlagStatus(usart_t *u, uint32_t f) { (void)u; (void)f; return tx_stuck ? RESET : SET; }
void USART_SendData(usart_t *u, uint8_t b) { (void)u; host_uart_tx(b); }
uint8_t USART_ReceiveData(usart_t *u) { (void)u; return 0; }
void IWDG_ReloadKey(void) { ++g_tick_ms; }
''', encoding="ascii")
        cmd = [
            cc, "-std=c99", "-Wall", "-Wextra", "-Werror", "-Wno-dangling-else", "-DEC800M_HOST_TEST",
            "-I", str(tmp), "-I", str(ROOT / "include"), str(tmp / "harness.c"), str(tmp / "stub.c"),
            str(ROOT / "src" / "ec800m.c"), str(ROOT / "src" / "ec800m_at_response.c"),
            str(ROOT / "src" / "peripherals.c"),
            str(ROOT / "src" / "at_config.c"), str(ROOT / "src" / "sms_command.c"),
            str(ROOT / "src" / "sms_ingress.c"), str(ROOT / "src" / "f39_command.c"),
            str(ROOT / "src" / "plate_encoding.c"),
            str(ROOT / "src" / "f39_config_adapter.c"), str(ROOT / "src" / "f39_reply.c"),
            str(ROOT / "src" / "terminal_identity.c"),
            "-Wl,--gc-sections", "-lm", "-o", str(tmp / "production.exe"),
        ]
        subprocess.run(cmd, check=True, cwd=ROOT)
        subprocess.run([str(tmp / "production.exe")], check=True, cwd=ROOT)


if __name__ == "__main__":
    test_f39_end_to_end()
    test_f39_production_chain()
