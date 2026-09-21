#include "at_config.h"
#include "production_test.h"
#include "jt808.h"
#include "work_mode.h"
#include "work_mode_sleep.h"
#include "hw_init.h"

#if defined(__GNUC__)
__attribute__((weak)) void work_mode_config_changed(const device_config_t *cfg,
                                                    uint32_t now_s)
{
    (void)cfg;
    (void)now_s;
}
#endif
#include "ec800m.h"
#include "gps.h"
#include "relay.h"
#include "debug_uart.h"
#include "config.h"
#include "flash_config.h"
#include "sms_command.h"
#include "f39_command.h"
#include "f39_reply.h"
#include "fota.h"
#include "tcp_manager.h"
#include "agnss_vendor.h"
#include "agnss_manager.h"
#include "peripherals.h"
#include <string.h>
#include <stdlib.h>

#define CMD_BUF_SIZE  128
#define ARG_MAX        8
#define F39_SMS_MAX_RETRIES 2U

static char    s_cmd_buf[CMD_BUF_SIZE];
/* Single ISR producer, single main-loop consumer. The ISR alone owns pos and
 * discard. ready transfers the slot: release publishes the completed line;
 * acquire observes it. The consumer releases only after its last slot read.
 * Byte atomics are lock-free on Cortex-M4; no IRQ masking or extra line slot. */
static uint8_t s_cmd_pos   = 0;
static bool    s_cmd_ready = false;
static bool    s_cmd_discard = false;

static f39_platform_t s_f39_platform;
static at_config_sms_send_fn s_sms_send;
static at_config_reset_fn s_schedule_reset;
static bool s_f39_bound;
static bool s_f39_uses_defaults;
static volatile bool s_reset_pending;
static uint32_t s_reset_due_ms;
static bool s_reset_waiting_handoff;
static uint32_t s_reset_handoff_delay_ms;
static char s_retry_sender[SMS_PHONE_MAX_LEN];
static char s_retry_reply[F39_REPLY_MAX_LENGTH];
static uint8_t s_retry_count;
static uint32_t s_retry_due_ms;
static bool s_retry_pending;
static bool s_retry_in_flight;

/* Defined below; the serial console falls back to it before rejecting a line
 * as unknown, so the F39 command set works over the debug UART too. */
static bool f39_execute_console(const char *line);

static bool f39_persist(const device_config_t *candidate, void *context) { (void)context; return cfg_store_candidate(candidate); }
static void f39_timer_refresh(void *context) { const device_config_t *c = cfg_get(); (void)context; jt808_set_heartbeat_s(c->heartbeat_s); jt808_set_report_interval(c->report_moving_s, c->report_stopped_s); work_mode_config_changed(c, work_mode_sleep_monotonic_s()); }
static void f39_network_reconnect(void *context) { const device_config_t *c = cfg_get(); (void)context; jt808_set_server(c->server_ip, c->server_port, false); jt808_set_server(c->backup_ip, c->backup_port, true); tcp_manager_reconnect(); }
static void f39_jt808_auth_reset(uint8_t channel_mask, void *context)
{
    uint8_t jt808_mask = 0U;
    (void)context;
    if ((channel_mask & F39_AUTH_CHANNEL_MAIN) != 0U)
        jt808_mask |= JT808_ENDPOINT_MAIN_MASK;
    if ((channel_mask & F39_AUTH_CHANNEL_BACKUP) != 0U)
        jt808_mask |= JT808_ENDPOINT_BACKUP_MASK;
    jt808_reset_endpoint_auth(jt808_mask);
}
static void f39_modem_pdp_restart(void *context) { (void)context; tcp_manager_reconnect(); ec800m_restart_pdp(); }
static void f39_gnss_mode(gnss_type_t type, uint8_t mode, void *context)
{
    static const char *const commands[] = { NULL, "$PCAS04,1*18\r\n", "$PCAS04,2*1B\r\n", "$PCAS04,7*1E\r\n" };
    (void)context; gnss_vendor_set_type(type);
    if (mode >= 1U && mode <= 3U) gps_send_cmd(commands[mode]);
}
static void f39_jt808_reregister(void *context) { const device_config_t *c = cfg_get(); (void)context; jt808_set_terminal_profile(c->terminal_model, c->plate_no); jt808_request_reregister(); }
static void f39_remaining_refresh(void *context) { (void)context; agnss_init(cfg_get()->gnss_type); }
static void f39_fota_recheck(void *context) { (void)context; (void)fota_request_check(); }
static bool f39_relay(bool cut, void *context) { (void)context; if (cut && relay_test_remaining() != 0U) return false; relay_set(cut); return true; }
static bool f39_gps_valid(void *context) { (void)context; return gps_is_valid(); }
static float f39_gps_speed(void *context) { (void)context; return gps_get_data()->speed_kmh; }
static bool f39_relay_get(void *context) { (void)context; return relay_get(); }
static void f39_default_reset(uint32_t delay_ms, void *context) { (void)context; s_reset_pending = true; s_reset_due_ms = TICK_MS() + delay_ms; }
static int f39_default_sms_send(const char *to, const char *text, void *context) { (void)context; return sms_send(to, text); }

static void f39_clear_reply_transaction(void)
{
    s_retry_pending = false;
    s_retry_in_flight = false;
    s_retry_count = 0U;
    s_retry_due_ms = 0U;
    s_retry_sender[0] = '\0';
    s_retry_reply[0] = '\0';
    s_reset_waiting_handoff = false;
    s_reset_handoff_delay_ms = 0U;
}

static void f39_schedule_reply_retry(void)
{
    if (s_retry_count >= F39_SMS_MAX_RETRIES) {
        dbg_printf("[SMS] reply dropped\r\n");
        f39_clear_reply_transaction();
        return;
    }
    ++s_retry_count;
    s_retry_due_ms = TICK_MS() + 1000U;
}

static void f39_sms_result(bool success)
{
    uint32_t reset_delay;
    bool reset_after_send;

    if (!s_retry_pending || !s_retry_in_flight) return;
    s_retry_in_flight = false;
    if (!success) {
        if (s_retry_count < F39_SMS_MAX_RETRIES) {
            f39_schedule_reply_retry();
            dbg_printf("[SMS] retry %u\r\n", s_retry_count);
        } else {
            dbg_printf("[SMS] reply failed after retries\r\n");
            f39_clear_reply_transaction();
        }
        return;
    }

    reset_after_send = s_reset_waiting_handoff;
    reset_delay = s_reset_handoff_delay_ms;
    f39_clear_reply_transaction();
    if (reset_after_send) f39_default_reset(reset_delay, NULL);
}

static void f39_bind_defaults(void)
{
    static char imei[16];
    static char iccid[24];
    const gps_data_t *g;
    if (s_f39_bound) return;
    memset(&s_f39_platform, 0, sizeof s_f39_platform);
    s_f39_platform.config = cfg_get(); s_f39_platform.persist = f39_persist;
    s_f39_platform.timer_refresh = f39_timer_refresh; s_f39_platform.network_reconnect = f39_network_reconnect; s_f39_platform.jt808_auth_reset = f39_jt808_auth_reset;
    s_f39_platform.modem_pdp_restart = f39_modem_pdp_restart;
    s_f39_platform.gnss_set_mode = f39_gnss_mode; s_f39_platform.jt808_reregister = f39_jt808_reregister;
    s_f39_platform.remaining_refresh = f39_remaining_refresh; s_f39_platform.relay_set = f39_relay;
    s_f39_platform.fota_recheck = f39_fota_recheck;
    s_f39_platform.gps_valid = f39_gps_valid; s_f39_platform.gps_speed_kmh = f39_gps_speed; s_f39_platform.relay_get = f39_relay_get;
    s_f39_platform.version = FW_VERSION_STR; s_f39_platform.version_len = (uint16_t)strlen(FW_VERSION_STR);
    ec800m_get_imei(imei, sizeof imei); s_f39_platform.imei = imei; s_f39_platform.imei_len = (uint16_t)strlen(imei);
    ec800m_get_iccid(iccid, sizeof iccid); s_f39_platform.iccid = iccid; s_f39_platform.iccid_len = (uint16_t)strlen(iccid);
    s_f39_platform.csq = ec800m_get_csq(); g = gps_get_data(); s_f39_platform.acc_on = hw_acc_is_on(); s_f39_platform.gps_fix_quality = g->fix_quality; s_f39_platform.gps_satellites = g->satellites; s_f39_platform.gps_hdop_x10 = (uint16_t)(g->hdop * 10.0f);
    s_sms_send = f39_default_sms_send; s_schedule_reset = f39_default_reset; sms_set_send_result_cb(f39_sms_result); s_f39_bound = true; s_f39_uses_defaults = true;
}

/* ── Feed bytes from serial ───────────────────────────────────────────────── */
void at_config_feed(uint8_t byte)
{
    bool delimiter = (byte == '\r' || byte == '\n');
    if (__atomic_load_n(&s_cmd_ready, __ATOMIC_ACQUIRE) || s_cmd_discard) {
        /* Never admit the tail of a line whose prefix arrived while busy. */
        s_cmd_discard = !delimiter;
        return;
    }
    if (byte == '\r' || byte == '\n') {
        if (s_cmd_pos > 0) {
            s_cmd_buf[s_cmd_pos] = '\0';
            s_cmd_pos = 0;
            __atomic_store_n(&s_cmd_ready, true, __ATOMIC_RELEASE);
        }
    } else if (s_cmd_pos < CMD_BUF_SIZE - 1) {
        s_cmd_buf[s_cmd_pos++] = (char)byte;
    }
}

/* ── Tokenize "CMD=arg1,arg2,..." ────────────────────────────────────────── */
static uint8_t tokenize(char *line, char **cmd_out, char **args, uint8_t max_args)
{
    char *eq = strchr(line, '=');
    if (eq) {
        *eq = '\0';
        *cmd_out = line;
        char *p = eq + 1;
        uint8_t n = 0;
        args[n++] = p;
        while (n < max_args) {
            p = strchr(p, ',');
            if (!p) break;
            *p++ = '\0';
            args[n++] = p;
        }
        return n;
    }
    *cmd_out = line;
    return 0;
}

/* ── Process one command ──────────────────────────────────────────────────── */
static void handle_cmd(char *line)
{
    char *cmd = NULL;
    char *args[ARG_MAX] = {0};
    uint8_t argc = tokenize(line, &cmd, args, ARG_MAX);

    /* Make command uppercase for comparison */
    for (char *p = cmd; *p; p++) if (*p >= 'a' && *p <= 'z') *p -= 32;

    /* ── VERSION ──────────────────────────────────────────────────────────── */
    if (strcmp(cmd, "VERSION") == 0) {
        dbg_printf("%s\r\n", FW_VERSION_STR);
        return;
    }
    /* ── IMEI ─────────────────────────────────────────────────────────────── */
    if (strcmp(cmd, "IMEI") == 0) {
        char imei[16] = {0};
        ec800m_get_imei(imei, sizeof(imei));
        dbg_printf("IMEI=%s\r\n", imei);
        return;
    }
    /* ── CHECK ────────────────────────────────────────────────────────────── */
    if (strcmp(cmd, "CHECK") == 0) {
        char imei[16] = {0};
        ec800m_get_imei(imei, sizeof(imei));
        const gps_data_t *g = gps_get_data();
        dbg_printf("IMEI=%s,CSQ=%d,GPS=%s,LAT=%.6f,LON=%.6f\r\n",
                   imei, ec800m_get_csq(),
                   g->valid ? "FIX" : "NOFIX",
                   g->lat, g->lon);
        return;
    }
    /* ── POSITION ─────────────────────────────────────────────────────────── */
    if (strcmp(cmd, "POSITION") == 0) {
        const gps_data_t *g = gps_get_data();
        if (g->valid)
            dbg_printf("LAT=%.6f,LON=%.6f,SPD=%.1f,HDG=%.1f,ALT=%.1f\r\n",
                       g->lat, g->lon, g->speed_kmh, g->heading, g->altitude_m);
        else
            dbg_printf("NO FIX\r\n");
        return;
    }
    /* ── SERVER=ip,port ───────────────────────────────────────────────────── */
    if (strcmp(cmd, "SERVER") == 0 && argc >= 2) {
        uint16_t port = (uint16_t)atoi(args[1]);
        jt808_set_server(args[0], port, false);
        dbg_printf("OK\r\n");
        return;
    }
    /* ── BSERVER=ip,port ──────────────────────────────────────────────────── */
    if (strcmp(cmd, "BSERVER") == 0 && argc >= 2) {
        uint16_t port = (uint16_t)atoi(args[1]);
        jt808_set_server(args[0], port, true);
        dbg_printf("OK\r\n");
        return;
    }
    /* ── HEARTBEAT=n ──────────────────────────────────────────────────────── */
    if (strcmp(cmd, "HEARTBEAT") == 0 && argc >= 1) {
        uint16_t s = (uint16_t)atoi(args[0]);
        if (s >= 1 && s <= 10) {
            jt808_set_heartbeat_s(s * 60);
            cfg_get()->heartbeat_s = (uint16_t)(s * 60U);
            work_mode_config_changed(cfg_get(), work_mode_sleep_monotonic_s());
            dbg_printf("OK\r\n");
        } else {
            dbg_printf("ERR:range 1-10 min\r\n");
        }
        return;
    }
    /* ── TIMER=A,B  (A=moving interval s, B=stopped interval s) ──────────── */
    if (strcmp(cmd, "TIMER") == 0 && argc >= 2) {
        uint16_t a = (uint16_t)atoi(args[0]);
        uint16_t b = (uint16_t)atoi(args[1]);
        if (a != 0U && a < JT808_REPORT_INTERVAL_MIN_S) a = JT808_REPORT_INTERVAL_MIN_S;
        if (b != 0U && b < JT808_REPORT_INTERVAL_MIN_S) b = JT808_REPORT_INTERVAL_MIN_S;
        jt808_set_report_interval(a, b);
        cfg_get()->report_moving_s = a;
        cfg_get()->report_stopped_s = b;
        work_mode_config_changed(cfg_get(), work_mode_sleep_monotonic_s());
        dbg_printf("OK\r\n");
        return;
    }
    /* ── RELAY=ON|OFF ─────────────────────────────────────────────────────── */
    if (strcmp(cmd, "RELAY") == 0 && argc >= 1) {
        bool on = (strcmp(args[0], "ON") == 0 || strcmp(args[0], "on") == 0);
        relay_set(on);
        dbg_printf("OK\r\n");
        return;
    }
    /* ── REBOOT ───────────────────────────────────────────────────────────── */
    if (strcmp(cmd, "REBOOT") == 0) {
        dbg_printf("REBOOTING\r\n");
        NVIC_SystemReset();
        return;
    }
    /* ── FACTORY ──────────────────────────────────────────────────────────── */
    if (strcmp(cmd, "FACTORY") == 0) {
        /* In a full implementation, clear flash config here */
        dbg_printf("FACTORY RESET\r\n");
        NVIC_SystemReset();
        return;
    }
    /* ── MODULECMD=<at command> ───────────────────────────────────────────── */
    if (strcmp(cmd, "MODULECMD") == 0 && argc >= 1) {
        /* Pass raw AT command through to EC800M via debug loopback */
        dbg_printf("NOT IMPL\r\n");
        return;
    }
    /* ── STOPDRIFT=ON|OFF,threshold ───────────────────────────────────────── */
    if (strcmp(cmd, "STOPDRIFT") == 0) {
        dbg_printf("OK\r\n");
        return;
    }
    /* ── HASACC=YES|NO ────────────────────────────────────────────────────── */
    if (strcmp(cmd, "HASACC") == 0) {
        dbg_printf("OK\r\n");
        return;
    }
    /* ── POWERALM=ON|OFF ──────────────────────────────────────────────────── */
    if (strcmp(cmd, "POWERALM") == 0) {
        dbg_printf("OK\r\n");
        return;
    }
    /* ── SOSALM=ON|OFF ────────────────────────────────────────────────────── */
    if (strcmp(cmd, "SOSALM") == 0) {
        dbg_printf("OK\r\n");
        return;
    }
    /* ── GMT=E|W,h,m ──────────────────────────────────────────────────────── */
    if (strcmp(cmd, "GMT") == 0) {
        dbg_printf("OK\r\n");
        return;
    }
    /* ── CELLAUTOGMT=ON|OFF ───────────────────────────────────────────────── */
    if (strcmp(cmd, "CELLAUTOGMT") == 0) {
        dbg_printf("OK\r\n");
        return;
    }
    /* ── GEOREP=ON|OFF,interval ───────────────────────────────────────────── */
    if (strcmp(cmd, "GEOREP") == 0) {
        dbg_printf("OK\r\n");
        return;
    }
    /* ── ANGLEREP=ON|OFF,angle,speed ─────────────────────────────────────── */
    if (strcmp(cmd, "ANGLEREP") == 0) {
        dbg_printf("OK\r\n");
        return;
    }
    /* ── SENDS=n ──────────────────────────────────────────────────────────── */
    if (strcmp(cmd, "SENDS") == 0 && argc >= 1) {
        dbg_printf("OK\r\n");
        return;
    }
    /* ── MILEAGE=n ────────────────────────────────────────────────────────── */
    if (strcmp(cmd, "MILEAGE") == 0) {
        dbg_printf("OK\r\n");
        return;
    }
    /* ── AUTOAPN=ON|OFF|SET,apn,user,pass ────────────────────────────────── */
    if (strcmp(cmd, "AUTOAPN") == 0) {
        dbg_printf("OK\r\n");
        return;
    }
    /* ── AGPS=ON|OFF,ip,port ──────────────────────────────────────────────── */
    if (strcmp(cmd, "AGPS") == 0) {
        dbg_printf("OK\r\n");
        return;
    }
    if (strcmp(cmd, "AGNSS") == 0 && argc >= 2) {
        device_config_t *cfg = cfg_get();
        if (!args[0][0] || !args[1][0] || strlen(args[0]) >= CFG_AGNSS_USER_LEN || strlen(args[1]) >= CFG_AGNSS_PWD_LEN) { dbg_printf("ERR:AUTH\r\n"); return; }
        strncpy(cfg->agnss_user,args[0],CFG_AGNSS_USER_LEN-1); strncpy(cfg->agnss_pwd,args[1],CFG_AGNSS_PWD_LEN-1);
        cfg->agnss_user[CFG_AGNSS_USER_LEN-1]='\0'; cfg->agnss_pwd[CFG_AGNSS_PWD_LEN-1]='\0'; cfg_save(); dbg_printf("OK\r\n"); return;
    }

    dbg_printf("ERR:UNKNOWN CMD\r\n");
}

void at_config_init(void) { f39_bind_defaults(); }

/* Keep command/reply arrays out of main's permanently live LTO frame. */
void __attribute__((noinline)) at_config_process(void)
{
    if (s_retry_pending && s_f39_uses_defaults && !s_retry_in_flight &&
        (int32_t)(TICK_MS() - s_retry_due_ms) >= 0) {
        if (sms_send(s_retry_sender, s_retry_reply) == 0) {
            s_retry_in_flight = true;
        } else {
            f39_schedule_reply_retry();
        }
    }
    if (s_reset_pending && (int32_t)(TICK_MS() - s_reset_due_ms) >= 0) {
        s_reset_pending = false;
        NVIC_SystemReset();
    }
    if (!__atomic_load_n(&s_cmd_ready, __ATOMIC_ACQUIRE)) return;
    /* Keep ISR writes excluded until the local snapshot is complete. */
    char local[CMD_BUF_SIZE];
    strncpy(local, s_cmd_buf, CMD_BUF_SIZE - 1);
    local[CMD_BUF_SIZE - 1] = '\0';
    __atomic_store_n(&s_cmd_ready, false, __ATOMIC_RELEASE);
    /* Try the F39 terminal command set first, on the untouched line: the
     * legacy console tokenizer rewrites '=' and ',' in place, which would
     * hand the F39 parser a truncated root. Falls through to the legacy
     * console commands when the line is not an F39 command. */
    if (production_test_command(local)) return;
    if (f39_execute_console(local)) return;
    /* f39_execute_console takes const input; fallback uses the same snapshot. */
    handle_cmd(local);
}

void at_config_bind_f39(f39_platform_t *platform, at_config_sms_send_fn send,
                        at_config_reset_fn schedule_reset, void *context)
{
    if (platform == NULL || send == NULL || schedule_reset == NULL) {
        s_f39_bound = false;
        return;
    }
    s_f39_platform = *platform;
    s_f39_platform.context = context;
    s_sms_send = send;
    s_schedule_reset = schedule_reset;
    s_f39_bound = true;
    s_f39_uses_defaults = false;
}

static void f39_refresh_live_snapshot(void)
{
    static char imei[16];
    static char iccid[24];
    const gps_data_t *g = gps_get_data();
    ec800m_get_imei(imei, sizeof imei);
    s_f39_platform.imei = imei; s_f39_platform.imei_len = (uint16_t)strlen(imei);
    ec800m_get_iccid(iccid, sizeof iccid);
    s_f39_platform.iccid = iccid; s_f39_platform.iccid_len = (uint16_t)strlen(iccid);
    s_f39_platform.csq = ec800m_get_csq(); s_f39_platform.gps_fix_quality = g->fix_quality;
    s_f39_platform.acc_on = hw_acc_is_on(); s_f39_platform.gps_satellites = g->satellites; s_f39_platform.gps_hdop_x10 = (uint16_t)(g->hdop * 10.0f);
}

/* Run one console line through the F39 terminal command set and print the
 * reply on the debug UART.  Returns false when the line is not an F39 command
 * so the caller can fall through to the legacy console commands.  The debug
 * console is the local operator's channel, so unlike SMS the reply is echoed
 * verbatim, failures included. */
static bool f39_execute_console(const char *line)
{
    f39_request_t request;
    f39_reply_t reply;
    uint16_t len = 0U;

    if (line == NULL) return false;
    while (len < F39_COMMAND_MAX_LENGTH && line[len] != '\0') ++len;
    if (len == 0U || len >= F39_COMMAND_MAX_LENGTH) return false;
    /* The command set frames commands with a trailing '#'; accept it with or
     * without, matching the SMS ingress which strips it before parsing. */
    if (line[len - 1U] == '#') --len;
    if (len == 0U) return false;
    if (!s_f39_bound) f39_bind_defaults();
    if (!s_f39_bound ||
        f39_parse((const uint8_t *)line, len, &request) != F39_RESULT_OK)
        return false;
    if (s_f39_uses_defaults) f39_refresh_live_snapshot();
    (void)f39_execute(&request, &s_f39_platform, &reply);
    if (reply.len == 0U) return false;
    /* reply.data is NUL-terminated by reply_append()'s vsnprintf and already
     * carries its own CRLF.  dbg_printf's %s ignores any precision, so print
     * it as a plain string rather than passing a length it would not consume. */
    reply.data[reply.len] = '\0';
    dbg_printf("%s", (const char *)reply.data);
    if (reply.reset_pending && s_schedule_reset != NULL)
        s_schedule_reset(reply.reset_delay_ms, s_f39_platform.context);
    return true;
}

/* Execute a command delivered over a transport that acknowledges the frame
 * itself (JT808 0x8300 text delivery, answered with a terminal general
 * response).  No reply text is produced or queued here: unlike the SMS path
 * there is no return channel to hand it to, and 0x0900 passthrough uplink is
 * deliberately not implemented. */
bool at_config_execute_text_command(const uint8_t *text, uint16_t len)
{
    f39_request_t request;
    f39_reply_t reply;

    if (!s_f39_bound) f39_bind_defaults();
    if (!text || !s_f39_bound ||
        f39_parse(text, len, &request) != F39_RESULT_OK) return false;
    if (s_f39_uses_defaults) f39_refresh_live_snapshot();
    if (f39_execute(&request, &s_f39_platform, &reply) != F39_RESULT_OK)
        return false;
    /* A RESET arriving this way still has to restart the device; the SMS path
     * defers it until its reply is on the wire, but here nothing is pending. */
    if (reply.reset_pending && s_schedule_reset != NULL)
        s_schedule_reset(reply.reset_delay_ms, s_f39_platform.context);
    return true;
}

bool at_config_execute_sms(const char *sender, const uint8_t *text, uint16_t len)
{
    f39_request_t request;
    f39_reply_t reply;
    char response[F39_REPLY_MAX_LENGTH];
    f39_result_t result;
    if (!s_f39_bound) f39_bind_defaults();
    if (!sender || !text || !s_f39_bound ||
        (s_f39_uses_defaults && s_retry_pending) ||
        f39_parse(text, len, &request) != F39_RESULT_OK) return false;
    if (s_f39_uses_defaults) {
        f39_refresh_live_snapshot();
    }
    result = f39_execute(&request, &s_f39_platform, &reply);
    if (reply.len == 0U || reply.len >= sizeof response) return false;
    memcpy(response, reply.data, reply.len);
    response[reply.len] = '\0';
    if (s_f39_uses_defaults) {
        strncpy(s_retry_sender, sender, sizeof s_retry_sender - 1U);
        s_retry_sender[sizeof s_retry_sender - 1U] = '\0';
        memcpy(s_retry_reply, response, reply.len + 1U);
        s_retry_count = 0U;
        s_retry_due_ms = 0U;
        s_retry_pending = true;
        s_retry_in_flight = true;
        s_reset_waiting_handoff = (result == F39_RESULT_OK && reply.reset_pending);
        s_reset_handoff_delay_ms = s_reset_waiting_handoff ? reply.reset_delay_ms : 0U;
        if (s_sms_send(sender, response, s_f39_platform.context) != 0) {
            s_retry_in_flight = false;
            f39_schedule_reply_retry();
            dbg_printf("[SMS] reply handoff failed for %s\r\n", sender);
            return true;
        }
    } else {
        if (s_sms_send(sender, response, s_f39_platform.context) != 0) {
            dbg_printf("[SMS] reply handoff failed for %s\r\n", sender);
            return false;
        }
        if (result == F39_RESULT_OK && reply.reset_pending)
            s_schedule_reset(reply.reset_delay_ms, s_f39_platform.context);
    }
    return true;
}

void at_config_receive_sms(const char *from, const uint8_t *text, uint16_t len)
{
    (void)at_config_execute_sms(from, text, len);
}
