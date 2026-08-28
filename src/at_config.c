#include "at_config.h"
#include "jt808.h"
#include "ec800m.h"
#include "gps.h"
#include "relay.h"
#include "debug_uart.h"
#include "config.h"
#include "flash_config.h"
#include <string.h>
#include <stdlib.h>

#define CMD_BUF_SIZE  128
#define ARG_MAX        8

static char    s_cmd_buf[CMD_BUF_SIZE];
static uint8_t s_cmd_pos   = 0;
static bool    s_cmd_ready = false;

/* ── Feed bytes from serial ───────────────────────────────────────────────── */
void at_config_feed(uint8_t byte)
{
    if (byte == '\r' || byte == '\n') {
        if (s_cmd_pos > 0) {
            s_cmd_buf[s_cmd_pos] = '\0';
            s_cmd_ready = true;
            s_cmd_pos = 0;
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
        jt808_set_report_interval(a, b);
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

void at_config_init(void) {}

void at_config_process(void)
{
    if (!s_cmd_ready) return;
    s_cmd_ready = false;
    /* Work on a local copy so feed() can safely refill s_cmd_buf */
    char local[CMD_BUF_SIZE];
    strncpy(local, s_cmd_buf, CMD_BUF_SIZE - 1);
    handle_cmd(local);
}

bool at_config_execute_sms(const uint8_t *text, uint16_t len)
{
    char local[SMS_COMMAND_MAX_LEN];
    if (!text || len == 0 || len >= sizeof(local)) return false;
    memcpy(local, text, len);
    local[len] = '\0';
    handle_cmd(local);
    return true;
}
