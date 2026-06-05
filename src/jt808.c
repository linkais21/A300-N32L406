#include "jt808.h"
#include "jt808_params.h"
#include "geofence.h"
#include "ec800m.h"
#include "gps.h"
#include "adc_monitor.h"
#include "config.h"
#include "hw_init.h"
#include "debug_uart.h"
#include "relay.h"
#include <string.h>
#include <stdlib.h>
#include <math.h>

/* ── Frame escaping (0x7e ↔ 0x7d 0x02,  0x7d ↔ 0x7d 0x01) ──────────────── */
#define FRAME_FLAG 0x7E
#define ESC_FLAG   0x7D

/* ── Persistent config (simple RAM copy; real device would use flash) ──────── */
typedef struct {
    char     server_ip[64];
    uint16_t server_port;
    char     backup_ip[64];
    uint16_t backup_port;
    uint16_t heartbeat_s;
    uint16_t report_moving_s;
    uint16_t report_stopped_s;
    char     auth_code[32];
} jt808_config_t;

static jt808_config_t s_cfg = {
    .server_ip        = "0.0.0.0",
    .server_port      = JT808_DEFAULT_PORT,
    .backup_ip        = "0.0.0.0",
    .backup_port      = JT808_DEFAULT_PORT,
    .heartbeat_s      = HEARTBEAT_DEFAULT_S,
    .report_moving_s  = 30,
    .report_stopped_s = 60,
};

static jt808_terminal_t s_term;
static uint16_t s_msg_sn = 0;
static uint8_t  s_tcp_ch = TCP_CH_MAIN;   /* active channel */

/* Registration state */
typedef enum {
    REG_STATE_IDLE = 0,
    REG_STATE_REGISTERING,
    REG_STATE_AUTHENTICATING,
    REG_STATE_ONLINE,
} reg_state_t;
static reg_state_t s_reg = REG_STATE_IDLE;

static uint32_t s_last_heartbeat_ms = 0;
static uint32_t s_last_location_ms  = 0;
static uint32_t s_alarm_flags       = 0;

/* RX reassembly */
#define JT808_RX_MAX  512
static uint8_t  s_rx_raw[JT808_RX_MAX];
static uint16_t s_rx_pos  = 0;
static bool     s_rx_in   = false;   /* inside frame */

/* ── BCD helpers ──────────────────────────────────────────────────────────── */
static void bcd_encode(const char *s, uint8_t *out, uint8_t len)
{
    for (uint8_t i = 0; i < len; i++) {
        uint8_t hi = s[i*2]     ? (uint8_t)(s[i*2]     - '0') : 0;
        uint8_t lo = s[i*2 + 1] ? (uint8_t)(s[i*2 + 1] - '0') : 0;
        out[i] = (hi << 4) | lo;
    }
}

/* ── Frame builder ────────────────────────────────────────────────────────── */
typedef struct {
    uint8_t  buf[512];
    uint16_t pos;
} frame_t;

static void frame_init(frame_t *f)   { f->pos = 0; }
static void frame_u8(frame_t *f, uint8_t v)   { f->buf[f->pos++] = v; }
static void frame_u16(frame_t *f, uint16_t v) { frame_u8(f, v>>8); frame_u8(f, v&0xFF); }
static void __attribute__((unused)) frame_u32(frame_t *f, uint32_t v)
{
    frame_u8(f, (v>>24)&0xFF); frame_u8(f, (v>>16)&0xFF);
    frame_u8(f, (v>>8)&0xFF);  frame_u8(f, v&0xFF);
}
static void frame_bytes(frame_t *f, const uint8_t *d, uint16_t n)
{
    memcpy(&f->buf[f->pos], d, n); f->pos += n;
}

static uint8_t checksum(const uint8_t *data, uint16_t len)
{
    uint8_t cs = 0;
    for (uint16_t i = 0; i < len; i++) cs ^= data[i];
    return cs;
}

/* Escape + wrap in 0x7E and send */
static int send_frame(frame_t *body)
{
    uint8_t out[1024];
    uint16_t o = 0;

    uint8_t cs = checksum(body->buf, body->pos);

    out[o++] = FRAME_FLAG;
    for (uint16_t i = 0; i < body->pos; i++) {
        uint8_t b = body->buf[i];
        if (b == FRAME_FLAG) { out[o++] = ESC_FLAG; out[o++] = 0x02; }
        else if (b == ESC_FLAG) { out[o++] = ESC_FLAG; out[o++] = 0x01; }
        else out[o++] = b;
    }
    /* checksum byte - also needs escaping */
    if (cs == FRAME_FLAG) { out[o++] = ESC_FLAG; out[o++] = 0x02; }
    else if (cs == ESC_FLAG) { out[o++] = ESC_FLAG; out[o++] = 0x01; }
    else out[o++] = cs;
    out[o++] = FRAME_FLAG;

    return ec800m_tcp_send(s_tcp_ch, out, o);
}

/* Build standard JT808 header */
static void build_header(frame_t *f, uint16_t msg_id, uint16_t body_len)
{
    frame_u16(f, msg_id);
    frame_u16(f, body_len & 0x03FF);   /* no fragmentation flag */
    /* Phone number (BCD, 6 bytes) */
    uint8_t phone_bcd[6] = {0};
    bcd_encode(s_term.phone, phone_bcd, 6);
    frame_bytes(f, phone_bcd, 6);
    frame_u16(f, ++s_msg_sn);
}

/* ── Message builders ─────────────────────────────────────────────────────── */
int jt808_send_register(void)
{
    /* body: province(2)+city(2)+manuf(5)+model(8)+term_id(7)+color(1)+plate */
    uint8_t model[8] = {0}, tid[7] = {0};
    memcpy(model, s_term.terminal_model,
           strlen(s_term.terminal_model) < 8 ? strlen(s_term.terminal_model) : 8);
    memcpy(tid,   s_term.terminal_id,
           strlen(s_term.terminal_id)    < 7 ? strlen(s_term.terminal_id)    : 7);

    uint8_t body[128];
    uint16_t pos = 0;
    body[pos++] = 0x00; body[pos++] = 0x01;   /* province */
    body[pos++] = 0x00; body[pos++] = 0x01;   /* city     */
    memcpy(&body[pos], s_term.manufacturer_id, 5); pos += 5;
    memcpy(&body[pos], model, 8);              pos += 8;
    memcpy(&body[pos], tid,   7);              pos += 7;
    body[pos++] = s_term.color;
    /* plate number GBK; write ASCII for now */
    uint8_t plen = (uint8_t)strlen(s_term.plate_no);
    memcpy(&body[pos], s_term.plate_no, plen); pos += plen;

    frame_t f; frame_init(&f);
    build_header(&f, MSG_TERMINAL_REGISTER, pos);
    frame_bytes(&f, body, pos);
    return send_frame(&f);
}

int jt808_send_auth(const char *code)
{
    uint8_t len = (uint8_t)strlen(code);
    frame_t f; frame_init(&f);
    build_header(&f, MSG_TERMINAL_AUTH, len);
    frame_bytes(&f, (const uint8_t *)code, len);
    return send_frame(&f);
}

int jt808_send_heartbeat(void)
{
    frame_t f; frame_init(&f);
    build_header(&f, MSG_HEARTBEAT, 0);
    return send_frame(&f);
}

int jt808_send_location(void)
{
    const gps_data_t *g = gps_get_data();
    uint32_t alm = s_alarm_flags;
    uint32_t status = 0;

    if (g->lat >= 0) status |= LOC_FLAG_NORTH_LAT;
    if (g->lon >= 0) status |= LOC_FLAG_EAST_LON;
    if (g->fix_quality > 0) status |= LOC_FLAG_GPS_FIXED;

    /* Body: alarm(4)+status(4)+lat(4)+lon(4)+altitude(2)+speed(2)+heading(2)+time(6BCD) */
    frame_t f; frame_init(&f);

    uint32_t lat_deg = (uint32_t)(fabs(g->lat) * 1e6);
    uint32_t lon_deg = (uint32_t)(fabs(g->lon) * 1e6);
    uint16_t speed   = (uint16_t)(g->speed_kmh * 10);
    uint16_t heading = (uint16_t)g->heading;
    uint16_t alt     = (uint16_t)g->altitude_m;

    uint8_t body[28];
    uint16_t p = 0;
    body[p++]=(alm>>24); body[p++]=(alm>>16); body[p++]=(alm>>8); body[p++]=alm;
    body[p++]=(status>>24); body[p++]=(status>>16); body[p++]=(status>>8); body[p++]=status;
    body[p++]=(lat_deg>>24); body[p++]=(lat_deg>>16); body[p++]=(lat_deg>>8); body[p++]=lat_deg;
    body[p++]=(lon_deg>>24); body[p++]=(lon_deg>>16); body[p++]=(lon_deg>>8); body[p++]=lon_deg;
    body[p++]=(alt>>8); body[p++]=alt;
    body[p++]=(speed>>8); body[p++]=speed;
    body[p++]=(heading>>8); body[p++]=heading;
    /* BCD time: YY MM DD HH mm SS */
    body[p++] = (uint8_t)(((g->year%100)/10)<<4 | (g->year%10));
    body[p++] = (uint8_t)((g->month/10)<<4  | (g->month%10));
    body[p++] = (uint8_t)((g->day/10)<<4    | (g->day%10));
    body[p++] = (uint8_t)((g->hour/10)<<4   | (g->hour%10));
    body[p++] = (uint8_t)((g->minute/10)<<4 | (g->minute%10));
    body[p++] = (uint8_t)((g->second/10)<<4 | (g->second%10));

    build_header(&f, MSG_LOCATION_REPORT, p);
    frame_bytes(&f, body, p);

    s_alarm_flags = 0;   /* clear after reporting */
    return send_frame(&f);
}

int jt808_send_general_resp(uint16_t resp_sn, uint16_t resp_id, uint8_t result)
{
    frame_t f; frame_init(&f);
    build_header(&f, MSG_TERMINAL_GENERAL_RESP, 5);
    frame_u16(&f, resp_sn);
    frame_u16(&f, resp_id);
    frame_u8(&f, result);
    return send_frame(&f);
}

/* Send an arbitrary message with a pre-built body (used by jt808_params.c).
 * resp_sn is currently unused (responses carry their own running serial). */
int jt808_send_raw(uint16_t msg_id, uint16_t resp_sn,
                   const uint8_t *body, uint16_t blen)
{
    (void)resp_sn;
    frame_t f; frame_init(&f);
    build_header(&f, msg_id, blen);
    if (blen) frame_bytes(&f, body, blen);
    return send_frame(&f);
}

/* ── RX frame parser ──────────────────────────────────────────────────────── */
static void process_frame(const uint8_t *raw, uint16_t raw_len)
{
    /* Unescape */
    uint8_t frame[JT808_RX_MAX];
    uint16_t flen = 0;
    for (uint16_t i = 0; i < raw_len && flen < JT808_RX_MAX; i++) {
        if (raw[i] == ESC_FLAG && i + 1 < raw_len) {
            if (raw[i+1] == 0x01)      frame[flen++] = ESC_FLAG;
            else if (raw[i+1] == 0x02) frame[flen++] = FRAME_FLAG;
            i++;
        } else {
            frame[flen++] = raw[i];
        }
    }
    if (flen < 13) return;  /* minimum: header(12) + checksum(1) */

    /* Verify checksum */
    uint8_t cs = checksum(frame, flen - 1);
    if (cs != frame[flen - 1]) {
        dbg_printf("[808] checksum error\r\n");
        return;
    }

    uint16_t msg_id     = ((uint16_t)frame[0] << 8) | frame[1];
    uint16_t body_prop  = ((uint16_t)frame[2] << 8) | frame[3];
    uint16_t body_len   = body_prop & 0x03FF;
    uint16_t serial_no  = ((uint16_t)frame[10] << 8) | frame[11];
    const uint8_t *body = &frame[12];

    switch (msg_id) {
    case MSG_PLATFORM_GENERAL_RESP:
        dbg_printf("[808] platform ack sn=%u\r\n", serial_no);
        break;

    case MSG_TERMINAL_REGISTER_RESP:
        if (body_len >= 3) {
            uint8_t result = body[2];
            if (result == 0) {
                /* auth code follows */
                uint8_t code_len = body_len - 3;
                if (code_len > 0 && code_len < sizeof(s_cfg.auth_code)) {
                    memcpy(s_cfg.auth_code, &body[3], code_len);
                    s_cfg.auth_code[code_len] = '\0';
                }
                jt808_send_auth(s_cfg.auth_code);
                s_reg = REG_STATE_AUTHENTICATING;
            }
        }
        break;

    case MSG_SET_TERMINAL_PARAM:    /* 0x8103 set parameters */
        jt808_params_handle_set(body, body_len, serial_no);
        break;

    case MSG_QUERY_TERMINAL_PARAM:  /* 0x8104 query parameters */
        jt808_params_handle_query(body, body_len, serial_no);
        break;

    case MSG_QUERY_TERMINAL_INFO:   /* 0x8107 query terminal attributes */
        jt808_params_handle_info_query(serial_no);
        break;

    case MSG_SET_POLYGON_AREA:      /* 0x8604 set polygon geofence */
        geofence_handle_jt808(body, body_len, serial_no);
        break;

    case MSG_LOCATION_QUERY:
        jt808_send_location();
        break;

    case MSG_TERMINAL_CTRL:
        /* Relay/reboot control */
        if (body_len >= 1) {
            uint8_t cmd_word = body[0];
            if (cmd_word == 1) {   /* remote relay off */
                relay_set(false);
            }
        }
        jt808_send_general_resp(serial_no, msg_id, 0);
        break;

    default:
        jt808_send_general_resp(serial_no, msg_id, 0);
        break;
    }

    /* If we were authenticating, receiving any valid message means auth OK */
    if (s_reg == REG_STATE_AUTHENTICATING && msg_id == MSG_PLATFORM_GENERAL_RESP)
        s_reg = REG_STATE_ONLINE;
}

/* ── Called from EC800M receive callback ─────────────────────────────────── */
void jt808_on_recv(uint8_t ch, const uint8_t *data, uint16_t len)
{
    (void)ch;
    for (uint16_t i = 0; i < len; i++) {
        uint8_t b = data[i];
        if (b == FRAME_FLAG) {
            if (s_rx_in && s_rx_pos > 0) {
                process_frame(s_rx_raw, s_rx_pos);
            }
            s_rx_in  = true;
            s_rx_pos = 0;
        } else if (s_rx_in) {
            if (s_rx_pos < JT808_RX_MAX) s_rx_raw[s_rx_pos++] = b;
        }
    }
}

/* ── State machine / process ─────────────────────────────────────────────── */
void jt808_init(const jt808_terminal_t *info)
{
    s_term = *info;
    s_msg_sn = 0;
    s_reg = REG_STATE_IDLE;
    ec800m_register_recv(jt808_on_recv);
}

void jt808_process(void)
{
    if (!ec800m_is_ready()) return;

    uint32_t now = TICK_MS();

    /* Ensure primary TCP channel is open */
    if (ec800m_tcp_state(TCP_CH_MAIN) == TCP_STATE_CLOSED) {
        if (ec800m_tcp_open(TCP_CH_MAIN, s_cfg.server_ip, s_cfg.server_port) == 0)
            s_reg = REG_STATE_REGISTERING;
        return;
    }
    if (ec800m_tcp_state(TCP_CH_MAIN) == TCP_STATE_OPENING) return;

    /* Registration flow */
    if (s_reg == REG_STATE_IDLE || s_reg == REG_STATE_REGISTERING) {
        static uint32_t reg_sent_ms = 0;
        if (now - reg_sent_ms > 5000) {
            jt808_send_register();
            reg_sent_ms = now;
        }
        return;
    }

    /* Heartbeat */
    if (now - s_last_heartbeat_ms > (uint32_t)s_cfg.heartbeat_s * 1000) {
        jt808_send_heartbeat();
        s_last_heartbeat_ms = now;
    }

    /* Location report */
    const gps_data_t *g = gps_get_data();
    uint16_t interval_s = (g->speed_kmh < 2.0f)
                          ? s_cfg.report_stopped_s
                          : s_cfg.report_moving_s;
    if (now - s_last_location_ms > (uint32_t)interval_s * 1000) {
        jt808_send_location();
        s_last_location_ms = now;
    }
}

/* ── Config accessors ─────────────────────────────────────────────────────── */
void jt808_set_server(const char *ip, uint16_t port, bool is_backup)
{
    if (!is_backup) {
        strncpy(s_cfg.server_ip,   ip, sizeof(s_cfg.server_ip)-1);
        s_cfg.server_port = port;
    } else {
        strncpy(s_cfg.backup_ip,   ip, sizeof(s_cfg.backup_ip)-1);
        s_cfg.backup_port = port;
    }
}

void jt808_get_server(char *ip_buf, uint16_t *port, bool is_backup)
{
    if (!is_backup) {
        strncpy(ip_buf, s_cfg.server_ip, 63);
        *port = s_cfg.server_port;
    } else {
        strncpy(ip_buf, s_cfg.backup_ip, 63);
        *port = s_cfg.backup_port;
    }
}

void jt808_trigger_alarm(uint32_t alarm_bit) { s_alarm_flags |= alarm_bit; }
void jt808_set_heartbeat_s(uint16_t s)       { s_cfg.heartbeat_s = s; }
uint16_t jt808_get_heartbeat_s(void)         { return s_cfg.heartbeat_s; }
void jt808_set_report_interval(uint16_t moving_s, uint16_t stopped_s)
{
    s_cfg.report_moving_s  = moving_s;
    s_cfg.report_stopped_s = stopped_s;
}
