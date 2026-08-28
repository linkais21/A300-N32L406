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
#include "flash_config.h"
#include "tcp_manager.h"
#include "terminal_identity.h"
#include "blind_zone.h"
#include "blind_zone_replay.h"
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

/* Registration state */
typedef enum {
    REG_STATE_IDLE = 0,
    REG_STATE_REGISTERING,
    REG_STATE_AUTHENTICATING,
    REG_STATE_ONLINE,
} reg_state_t;
static reg_state_t s_reg = REG_STATE_IDLE;
static bool s_force_registration;
static uint32_t s_register_sent_ms;
static uint32_t s_registration_generation;
static uint32_t s_active_registration_generation;
static uint16_t s_active_registration_sn;
static bool s_registration_response_active;
static uint32_t s_identity_log_ms;
static bool s_identity_logged;
static uint16_t s_auth_serial;
static uint8_t s_auth_channel;
static uint32_t s_auth_generation;
static bool s_auth_active;

static uint32_t s_last_heartbeat_ms = 0;
static uint32_t s_last_location_ms  = 0;
static uint32_t s_alarm_flags       = 0;

/* RX reassembly */
#define JT808_RX_MAX  512
typedef struct {
    uint8_t raw[JT808_RX_MAX];
    uint16_t pos;
    uint32_t generation;
    bool in_frame;
} rx_assembly_t;
static rx_assembly_t s_rx[EC800M_CH_MAX];

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

    if (s_reg == REG_STATE_ONLINE) {
        if (!jt808_is_online()) return -1;
        return ec800m_tcp_send(s_auth_channel, out, o);
    }
    {
        uint8_t channel = tcp_manager_active_ch();
        if (!tcp_manager_ch_online(channel)) return -1;
        return ec800m_tcp_send(channel, out, o);
    }
}

static int send_frame_channel(frame_t *body, uint8_t channel)
{
    uint8_t out[1024];
    uint16_t o = 0U;
    uint8_t cs = checksum(body->buf, body->pos);
    uint16_t i;
    if (!tcp_manager_ch_online(channel)) return -1;
    out[o++] = FRAME_FLAG;
    for (i = 0U; i < body->pos; ++i) {
        uint8_t b = body->buf[i];
        if (b == FRAME_FLAG) { out[o++] = ESC_FLAG; out[o++] = 0x02U; }
        else if (b == ESC_FLAG) { out[o++] = ESC_FLAG; out[o++] = 0x01U; }
        else out[o++] = b;
    }
    if (cs == FRAME_FLAG) { out[o++] = ESC_FLAG; out[o++] = 0x02U; }
    else if (cs == ESC_FLAG) { out[o++] = ESC_FLAG; out[o++] = 0x01U; }
    else out[o++] = cs;
    out[o++] = FRAME_FLAG;
    return ec800m_tcp_send(channel, out, o);
}

/* Build standard JT808 header */
static void build_header(frame_t *f, uint16_t msg_id, uint16_t body_len)
{
    frame_u16(f, msg_id);
    frame_u16(f, body_len & 0x03FF);   /* no fragmentation flag */
    /* phone number rule: take last 11 digits of IMEI, left-pad with '0' to form 12 digits */
    uint8_t phone_bcd[6] = {0};
    char phone[13] = "000000000000";
    char imei[16] = {0};
    ec800m_get_imei(imei, sizeof(imei));
    uint8_t ilen = (uint8_t)strlen(imei);
    if (ilen >= 11) {
        phone[0] = '0';
        strncpy(phone + 1, imei + ilen - 11, 11);
        phone[12] = '\0';
    }
    bcd_encode(phone, phone_bcd, 6);
    frame_bytes(f, phone_bcd, 6);
    frame_u16(f, ++s_msg_sn);
}

static bool refresh_terminal_identity(void)
{
    char terminal_id[8];
    if (!terminal_identity_load(terminal_id)) return false;
    memcpy(s_term.terminal_id, terminal_id, sizeof(s_term.terminal_id));
    return true;
}

static void log_identity_invalid(uint32_t now)
{
    if (!s_identity_logged || now - s_identity_log_ms >= 5000U) {
        dbg_printf("[808] identity invalid\r\n");
        s_identity_log_ms = now;
        s_identity_logged = true;
    }
}

static void identity_valid(void)
{
    s_identity_logged = false;
}

static void invalidate_registration_response(void)
{
    ++s_registration_generation;
    s_registration_response_active = false;
}

/* ── Message builders ─────────────────────────────────────────────────────── */
static int send_register_current_identity(void)
{
    /* body: province(2)+city(2)+manuf(5)+model(20)+term_id(7)+color(1)+plate
     * 808-2013 Table 7: 终端型号 BYTE[20], 终端ID BYTE[7] */
    uint8_t model[20] = {0}, tid[7] = {0};
    memcpy(model, s_term.terminal_model,
           strlen(s_term.terminal_model) < 20 ? strlen(s_term.terminal_model) : 20);
    memcpy(tid,   s_term.terminal_id,
           strlen(s_term.terminal_id)    < 7 ? strlen(s_term.terminal_id)    : 7);

    uint8_t body[128];
    uint16_t pos = 0;
    body[pos++] = 0x00; body[pos++] = 0x01;   /* province */
    body[pos++] = 0x00; body[pos++] = 0x01;   /* city     */
    memcpy(&body[pos], s_term.manufacturer_id, 5); pos += 5;
    memcpy(&body[pos], model, 20);             pos += 20;
    memcpy(&body[pos], tid,   7);              pos += 7;
    body[pos++] = s_term.color;
    /* plate number GBK; write ASCII for now */
    uint8_t plen = (uint8_t)strlen(s_term.plate_no);
    memcpy(&body[pos], s_term.plate_no, plen); pos += plen;

    frame_t f; frame_init(&f);
    build_header(&f, MSG_TERMINAL_REGISTER, pos);
    frame_bytes(&f, body, pos);
    {
        int result = send_frame(&f);
        if (result == 0) {
            s_active_registration_sn = s_msg_sn;
            s_active_registration_generation = s_registration_generation;
            s_registration_response_active = true;
        }
        return result;
    }
}

int jt808_send_register(void)
{
    if (!refresh_terminal_identity()) return -1;
    return send_register_current_identity();
}

void jt808_request_reregister(void)
{
    invalidate_registration_response();
    s_force_registration = true;
    s_reg = REG_STATE_IDLE;
    s_register_sent_ms = 0U;
    s_registration_response_active = false;
    s_term.terminal_id[0] = '\0';
}

int jt808_send_auth(const char *code)
{
    uint8_t len = (uint8_t)strlen(code);
    frame_t f; frame_init(&f);
    build_header(&f, MSG_TERMINAL_AUTH, len);
    s_auth_serial = s_msg_sn;
    s_auth_channel = tcp_manager_active_ch();
    s_auth_generation = tcp_manager_session_generation(s_auth_channel);
    s_auth_active = true;
    frame_bytes(&f, (const uint8_t *)code, len);
    return send_frame_channel(&f, s_auth_channel);
}

int jt808_send_heartbeat(void)
{
    frame_t f; frame_init(&f);
    build_header(&f, MSG_HEARTBEAT, 0);
    return send_frame(&f);
}

static uint16_t encode_location_body(uint8_t body[BLIND_ZONE_LOCATION_MAX])
{
    const gps_data_t *g = gps_get_data();
    uint32_t alm = s_alarm_flags;
    uint32_t status = 0;

    /* ACC状态：PA3 高电平=ACC ON */
    if (GPIO_ReadInputDataBit(ACC_DET_PORT, ACC_DET_PIN) != Bit_RESET)
        status |= LOC_FLAG_ACC_ON;
    /* 808-2013: bit2=1表示西经(默认东经不置位), bit3=1表示南纬(默认北纬不置位) */
    if (g->lon < 0) status |= LOC_FLAG_WEST_LON;
    if (g->lat < 0) status |= LOC_FLAG_SOUTH_LAT;
    if (g->fix_quality > 0) status |= LOC_FLAG_GPS_FIXED;

    uint32_t lat_deg = (uint32_t)(fabs(g->lat) * 1e6);
    uint32_t lon_deg = (uint32_t)(fabs(g->lon) * 1e6);
    uint16_t speed   = (uint16_t)(g->speed_kmh * 10);
    uint16_t heading = (uint16_t)g->heading;
    uint16_t alt     = (uint16_t)g->altitude_m;

    /* 强制字段(28字节) + 附加项0x31卫星颗数(3字节) + 附加项0x30信号强度(3字节) */
    uint16_t p = 0;
    body[p++]=(alm>>24); body[p++]=(alm>>16); body[p++]=(alm>>8); body[p++]=alm;
    body[p++]=(status>>24); body[p++]=(status>>16); body[p++]=(status>>8); body[p++]=status;
    body[p++]=(lat_deg>>24); body[p++]=(lat_deg>>16); body[p++]=(lat_deg>>8); body[p++]=lat_deg;
    body[p++]=(lon_deg>>24); body[p++]=(lon_deg>>16); body[p++]=(lon_deg>>8); body[p++]=lon_deg;
    body[p++]=(alt>>8); body[p++]=alt;
    body[p++]=(speed>>8); body[p++]=speed;
    body[p++]=(heading>>8); body[p++]=heading;
    /* UTC+8 时区转换，处理日期进位 */
    uint8_t t_hour  = g->hour + 8;
    uint8_t t_day   = g->day;
    uint8_t t_month = g->month;
    uint16_t t_year = g->year;
    if (t_hour >= 24) {
        t_hour -= 24;
        t_day++;
        /* 简单月末处理：按31天月判断，闰年2月不单独处理 */
        static const uint8_t days_in_month[] = {0,31,28,31,30,31,30,31,31,30,31,30,31};
        uint8_t dim = (t_month == 2 && (t_year%4==0)) ? 29 : days_in_month[t_month];
        if (t_day > dim) {
            t_day = 1;
            t_month++;
            if (t_month > 12) { t_month = 1; t_year++; }
        }
    }
    /* BCD时间: YY MM DD HH mm SS (北京时间) */
    body[p++] = (uint8_t)(((t_year%100)/10)<<4 | (t_year%10));
    body[p++] = (uint8_t)((t_month/10)<<4  | (t_month%10));
    body[p++] = (uint8_t)((t_day/10)<<4    | (t_day%10));
    body[p++] = (uint8_t)((t_hour/10)<<4   | (t_hour%10));
    body[p++] = (uint8_t)((g->minute/10)<<4 | (g->minute%10));
    body[p++] = (uint8_t)((g->second/10)<<4 | (g->second%10));
    /* 附加信息项 0x31: GNSS定位卫星数(1字节) */
    body[p++] = 0x31;
    body[p++] = 0x01;
    body[p++] = g->satellites;
    /* 附加信息项 0x30: 无线通信网络信号强度(1字节) — CSQ值 */
    body[p++] = 0x30;
    body[p++] = 0x01;
    body[p++] = (uint8_t)ec800m_get_csq();

    return p;
}

int jt808_send_location(void)
{
    blind_zone_record_t record;
    frame_t f;
    int result = -1;

    record.length = (uint8_t)encode_location_body(record.location);
    if (jt808_is_online()) {
        frame_init(&f);
        build_header(&f, MSG_LOCATION_REPORT, record.length);
        frame_bytes(&f, record.location, record.length);
        result = send_frame(&f);
        if (result == 0) {
            s_alarm_flags = 0;
            return 0;
        }
    }

    {
        blind_zone_result_t stored = blind_zone_append(&record);
        if (stored == BLIND_ZONE_OK || stored == BLIND_ZONE_PENDING) {
            s_alarm_flags = 0;
            return 0;
        }
        if (stored == BLIND_ZONE_BUSY) return -2;
    }
    return result;
}

static int send_location_only(uint16_t message_id)
{
    uint8_t body[BLIND_ZONE_LOCATION_MAX];
    frame_t frame;
    uint16_t length = encode_location_body(body);
    if (!jt808_is_online()) return -1;
    frame_init(&frame);
    build_header(&frame, message_id, length);
    frame_bytes(&frame, body, length);
    return send_frame(&frame);
}

static void process_location_timer(uint32_t now)
{
    const gps_data_t *g = gps_get_data();
    uint16_t interval_s = s_cfg.report_stopped_s;
    if (g->valid)
        interval_s = (g->speed_kmh < 2.0f) ? s_cfg.report_stopped_s
                                           : s_cfg.report_moving_s;
    if (interval_s == 0U) return;
    if (now - s_last_location_ms > (uint32_t)interval_s * 1000U) {
        int result = jt808_send_location();
        if (result != -2) s_last_location_ms = now;
    }
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

int jt808_send_raw_tracked(uint16_t msg_id, const uint8_t *body,
                           uint16_t blen, uint16_t *serial_out)
{
    frame_t f;
    if (serial_out == NULL || blen > sizeof(f.buf) - 12U ||
        (blen != 0U && body == NULL))
        return -1;
    frame_init(&f);
    build_header(&f, msg_id, blen);
    *serial_out = s_msg_sn;
    if (blen != 0U) frame_bytes(&f, body, blen);
    if (!jt808_is_online()) return -1;
    return send_frame_channel(&f, s_auth_channel);
}

/* ── RX frame parser ──────────────────────────────────────────────────────── */
static void process_frame(uint8_t channel, uint32_t generation,
                          const uint8_t *raw, uint16_t raw_len)
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
    if ((body_prop & 0x2000U) != 0U || body_len != flen - 13U) return;
    if (s_reg == REG_STATE_ONLINE &&
        (channel != s_auth_channel || generation != s_auth_generation))
        return;

    switch (msg_id) {
    case MSG_PLATFORM_GENERAL_RESP:
        if (body_len == 5U) {
            uint16_t reply_serial = ((uint16_t)body[0] << 8) | body[1];
            uint16_t reply_msg_id = ((uint16_t)body[2] << 8) | body[3];
            if (channel == s_auth_channel && generation == s_auth_generation)
                blind_zone_replay_on_general_ack(reply_serial, reply_msg_id, body[4]);
            if (s_reg == REG_STATE_AUTHENTICATING && s_auth_active &&
                channel == s_auth_channel && generation == s_auth_generation &&
                reply_serial == s_auth_serial &&
                reply_msg_id == MSG_TERMINAL_AUTH && body[4] == 0U) {
                s_auth_active = false;
                s_reg = REG_STATE_ONLINE;
                dbg_printf("[808] online\r\n");
            }
        }
        break;

    case MSG_TERMINAL_REGISTER_RESP:
        if (body_len >= 3 && s_reg == REG_STATE_REGISTERING &&
            s_registration_response_active &&
            s_active_registration_generation == s_registration_generation &&
            (((uint16_t)body[0] << 8) | body[1]) == s_active_registration_sn) {
            uint8_t result = body[2];
            s_registration_response_active = false;
            dbg_printf("[808] reg_resp result=%u t=%us\r\n", result, (unsigned)(TICK_MS()/1000));
            if (result == 0) {
                s_force_registration = false;
                uint8_t code_len = body_len - 3;
                if (code_len > 0 && code_len < sizeof(s_cfg.auth_code)) {
                    memcpy(s_cfg.auth_code, &body[3], code_len);
                    s_cfg.auth_code[code_len] = '\0';
                    device_config_t *c = cfg_get();
                    strncpy(c->auth_code, s_cfg.auth_code, sizeof(c->auth_code) - 1);
                    cfg_save();
                }
                jt808_send_auth(s_cfg.auth_code);
                s_reg = REG_STATE_AUTHENTICATING;
            } else if (result == 3) {
                s_force_registration = false;
                jt808_send_auth(s_cfg.auth_code);
                s_reg = REG_STATE_AUTHENTICATING;
            } else {
                dbg_printf("[808] register rejected result=%u\r\n", result);
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
        (void)send_location_only(MSG_LOCATION_QUERY_RESP);
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

}

bool jt808_is_online(void)
{
    return s_reg == REG_STATE_ONLINE && tcp_manager_ch_online(s_auth_channel) &&
           tcp_manager_session_generation(s_auth_channel) == s_auth_generation;
}
uint8_t jt808_online_channel(void) { return s_auth_channel; }
uint32_t jt808_online_generation(void) { return s_auth_generation; }

/* ── Called from EC800M receive callback ─────────────────────────────────── */
void jt808_on_recv(uint8_t ch, const uint8_t *data, uint16_t len)
{
    rx_assembly_t *rx;
    uint32_t generation;
    if (ch >= EC800M_CH_MAX) return;
    rx = &s_rx[ch];
    generation = tcp_manager_session_generation(ch);
    if (rx->generation != generation) {
        rx->generation = generation;
        rx->pos = 0U;
        rx->in_frame = false;
    }
    for (uint16_t i = 0; i < len; i++) {
        uint8_t b = data[i];
        if (b == FRAME_FLAG) {
            if (rx->in_frame && rx->pos > 0U) {
                process_frame(ch, generation, rx->raw, rx->pos);
            }
            rx->in_frame = true;
            rx->pos = 0U;
        } else if (rx->in_frame) {
            if (rx->pos < JT808_RX_MAX) rx->raw[rx->pos++] = b;
        }
    }
}

/* ── State machine / process ─────────────────────────────────────────────── */
void jt808_init(const jt808_terminal_t *info)
{
    s_term = *info;
    s_msg_sn = 0;
    s_reg = REG_STATE_IDLE;
    s_force_registration = false;
    s_register_sent_ms = 0U;
    s_registration_generation = 1U;
    s_active_registration_generation = 0U;
    s_active_registration_sn = 0U;
    s_registration_response_active = false;
    s_identity_log_ms = 0U;
    s_identity_logged = false;
    s_auth_active = false;
    s_auth_serial = 0U;
    s_auth_channel = TCP_CH_MAIN;
    s_auth_generation = 0U;
    memset(s_rx, 0, sizeof(s_rx));
    blind_zone_replay_reset();
    /* restore auth code from flash so reconnects skip re-registration */
    if (info->auth_code[0])
        strncpy(s_cfg.auth_code, info->auth_code, sizeof(s_cfg.auth_code) - 1);
    ec800m_register_recv(jt808_on_recv);
}

void jt808_process(void)
{
    uint32_t now = TICK_MS();
    process_location_timer(now);
    if (!ec800m_is_ready()) return;

    /* TCP connection is managed by tcp_manager; wait for at least one channel. */
    if (!tcp_manager_is_online()) {
        if (s_reg != REG_STATE_IDLE) {
            invalidate_registration_response();
            s_reg = REG_STATE_IDLE;
        }
        return;
    }
    if (s_reg == REG_STATE_ONLINE && !jt808_is_online()) {
        s_reg = REG_STATE_IDLE;
        s_auth_active = false;
        memset(s_rx, 0, sizeof(s_rx));
        blind_zone_replay_reset();
    }

    /* Registration / authentication flow.
     * Protocol rule: after each connection, authenticate immediately if we have
     * an auth code from a previous successful registration.  Only send 0x0100
     * register when no auth code is known. */
    if (s_reg == REG_STATE_IDLE) {
        if (!refresh_terminal_identity()) {
            log_identity_invalid(now);
            return;
        }
        identity_valid();
        if (s_cfg.auth_code[0] && !s_force_registration) {
            dbg_printf("[808] auth -> %s\r\n", s_cfg.auth_code);
            jt808_send_auth(s_cfg.auth_code);
            s_reg = REG_STATE_AUTHENTICATING;
        } else {
            dbg_printf("[808] register\r\n");
            if (send_register_current_identity() == 0) {
                s_reg = REG_STATE_REGISTERING;
                s_register_sent_ms = now;
            }
        }
        s_last_heartbeat_ms = now;
        s_last_location_ms  = now;
        return;
    }
    if (s_reg == REG_STATE_REGISTERING) {
        if (now - s_register_sent_ms >= 5000U) {
            dbg_printf("[808] register retry\r\n");
            if (!refresh_terminal_identity()) {
                invalidate_registration_response();
                log_identity_invalid(now);
                s_register_sent_ms = now;
                return;
            }
            identity_valid();
            if (send_register_current_identity() != 0) {
                s_register_sent_ms = now;
                return;
            }
            s_register_sent_ms = now;
        }
        return;
    }
    if (s_reg == REG_STATE_AUTHENTICATING) {
        static uint32_t auth_sent_ms = 0;
        if (auth_sent_ms == 0) auth_sent_ms = now;
        if (now - auth_sent_ms > 3000) {
            dbg_printf("[808] auth retry\r\n");
            jt808_send_auth(s_cfg.auth_code);
            auth_sent_ms = now;
        }
        return;
    }

    /* Heartbeat */
    if (now - s_last_heartbeat_ms > (uint32_t)s_cfg.heartbeat_s * 1000) {
        jt808_send_heartbeat();
        s_last_heartbeat_ms = now;
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
    s_cfg.report_moving_s =
        (moving_s != 0U && moving_s < JT808_REPORT_INTERVAL_MIN_S)
            ? JT808_REPORT_INTERVAL_MIN_S : moving_s;
    s_cfg.report_stopped_s =
        (stopped_s != 0U && stopped_s < JT808_REPORT_INTERVAL_MIN_S)
            ? JT808_REPORT_INTERVAL_MIN_S : stopped_s;
}
