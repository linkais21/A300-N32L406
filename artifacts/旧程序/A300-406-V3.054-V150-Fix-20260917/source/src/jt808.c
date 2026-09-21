static inline int trial_discard_trace(const char *fmt, ...)
{ (void)fmt; return 0; }
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
#include "i2c_accel.h"
#include "terminal_identity.h"
#include "jt808_session.h"
#include "jt808_terminal_info.h"
#include "blind_zone.h"
#include "blind_zone_replay.h"
#include "log_platform.h"
#include "motion_corner.h"
#include "work_mode.h"
#include "work_mode_sleep.h"
#include "at_config.h"
#include <string.h>
#include <stdlib.h>
#include <math.h>

/* Host contract tests may compile jt808.c without the optional pure policy
 * translation unit.  Keep those builds linkable while production Makefile
 * supplies the real implementation. */
#if defined(__GNUC__)
extern void motion_corner_init(motion_corner_ctx_t *, const motion_corner_config_t *) __attribute__((weak));
extern motion_corner_event_t motion_corner_step(motion_corner_ctx_t *, const motion_corner_sample_t *) __attribute__((weak));
extern bool motion_corner_peek_candidate(const motion_corner_ctx_t *, motion_corner_candidate_t *) __attribute__((weak));
extern void motion_corner_consume_candidate(motion_corner_ctx_t *) __attribute__((weak));
extern uint8_t motion_corner_pending_candidates(const motion_corner_ctx_t *) __attribute__((weak));
#endif

static void __attribute__((unused)) corner_init_safe(motion_corner_ctx_t *ctx)
{ if (motion_corner_init != NULL) motion_corner_init(ctx, NULL); else memset(ctx, 0, sizeof(*ctx)); }
static motion_corner_event_t __attribute__((unused)) corner_step_safe(motion_corner_ctx_t *ctx,
                                              const motion_corner_sample_t *sample)
{ motion_corner_event_t e = { false, MOTION_CORNER_REASON_NONE, false };
  return motion_corner_step != NULL ? motion_corner_step(ctx, sample) : e; }

/* ── Frame escaping (0x7e ↔ 0x7d 0x02,  0x7d ↔ 0x7d 0x01) ──────────────── */
#define FRAME_FLAG 0x7E
#define ESC_FLAG   0x7D
#define JT808_LOCATION_ONLINE_MAX 67U

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
    char     backup_auth_code[32];
} jt808_config_t;

static jt808_config_t s_cfg = {
    .server_ip        = "0.0.0.0",
    .server_port      = JT808_DEFAULT_PORT,
    .backup_ip        = "0.0.0.0",
    .backup_port      = JT808_DEFAULT_PORT,
    .heartbeat_s      = HEARTBEAT_DEFAULT_S,
    .report_moving_s  = 30,
    .report_stopped_s = 180,
};

static jt808_terminal_t s_term;
static uint16_t s_msg_sn = 0;

static uint32_t s_identity_log_ms;
static bool s_identity_logged;
static bool s_boot_identity_logged;
static terminal_identity_result_t s_boot_identity_source;
static jt808_session_t s_sessions[2];
static uint8_t s_response_channel;

#define JT808_TERMINAL_INFO_RETRY_MS   5000U
#define JT808_TERMINAL_INFO_BACKOFF_MS 60000U
#define JT808_TERMINAL_INFO_MAX_TRIES  3U

typedef struct {
    uint32_t retry_at_ms;
    uint8_t attempts;
    bool pending;
    bool sent;
} boot_terminal_info_t;

static boot_terminal_info_t s_boot_terminal_info[2];

static jt808_session_t *session_for_channel(uint8_t channel)
{
    if (channel == TCP_CH_MAIN) return &s_sessions[0];
    if (channel == TCP_CH_BACKUP) return &s_sessions[1];
    return NULL;
}

static const char *auth_for_channel(uint8_t channel)
{
    return channel == TCP_CH_MAIN ? s_cfg.auth_code : s_cfg.backup_auth_code;
}

static const char *jt808_action_name(jt808_session_action_t action)
{
    switch (action) {
    case JT808_ACTION_REGISTER:
        return "REGISTER";
    case JT808_ACTION_AUTH:
        return "AUTH";
    default:
        return "NONE";
    }
}

static void clear_channel_auth(uint8_t channel)
{
    char *auth = channel == TCP_CH_MAIN ? s_cfg.auth_code :
                 channel == TCP_CH_BACKUP ? s_cfg.backup_auth_code : NULL;
    if (auth != NULL && cfg_set_auth_code(channel, "")) auth[0] = '\0';
}

/* Heartbeat cadence is expressed in a sleep-aware monotonic seconds clock.
 * STOP1 suspends SysTick, so TICK_MS() does not advance while the modem link
 * is serviced from the RTC wake windows. */
static uint32_t s_last_heartbeat_s = 0;
static uint32_t s_last_location_ms  = 0;
static uint32_t s_alarm_flags       = 0;
static bool s_logical_acc_override_set;
static bool s_logical_acc_on;
static bool s_append_pending;
static blind_zone_record_t s_append_pending_record;
static motion_corner_ctx_t s_motion_corner;
static bool s_corner_append_pending;
static blind_zone_record_t s_corner_pending_record;
static motion_corner_candidate_t s_corner_pending_candidate;
static gps_data_t s_corner_snapshots[MOTION_CORNER_CANDIDATE_CAPACITY];
static uint32_t s_corner_snapshot_ms[MOTION_CORNER_CANDIDATE_CAPACITY];
static uint32_t s_corner_last_heading_ms;

#if defined(__GNUC__)
extern uint32_t work_mode_sleep_monotonic_s(void) __attribute__((weak));
#endif

static uint32_t jt808_monotonic_s(void)
{
#if defined(__GNUC__)
    if (work_mode_sleep_monotonic_s != NULL)
        return work_mode_sleep_monotonic_s();
#endif
    return TICK_MS() / 1000U;
}

/* RX reassembly */
#define JT808_RX_MAX  512
typedef struct {
    uint8_t raw[JT808_RX_MAX];
    uint16_t pos;
    /* Use the gap before generation for this flag (RAM-only state). */
    bool in_frame;
    uint32_t generation;
} rx_assembly_t;
static rx_assembly_t s_rx[2];

typedef struct {
    char code[CFG_AUTH_LEN];
    uint32_t generation;
    bool valid;
} pending_auth_t;
static pending_auth_t s_pending_auth[2];

static rx_assembly_t *rx_for_channel(uint8_t channel)
{
    if (channel == TCP_CH_MAIN) return &s_rx[0];
    if (channel == TCP_CH_BACKUP) return &s_rx[1];
    return NULL;
}

static pending_auth_t *pending_auth_for_channel(uint8_t channel)
{
    if (channel == TCP_CH_MAIN) return &s_pending_auth[0];
    if (channel == TCP_CH_BACKUP) return &s_pending_auth[1];
    return NULL;
}

/* ── Frame builder ────────────────────────────────────────────────────────── */
typedef struct {
    uint16_t pos;
    uint16_t wire_len;
    bool prepared;
} frame_t;

typedef struct {
    uint8_t data[1028];
    bool busy;
} jt808_tx_workspace_t;
static jt808_tx_workspace_t s_tx_workspace;

static bool frame_init(frame_t *f)
{
    if (f == NULL || s_tx_workspace.busy) return false;
    s_tx_workspace.busy = true;
    f->pos = 0U;
    f->wire_len = 0U;
    f->prepared = false;
    return true;
}
static void frame_release(void) { s_tx_workspace.busy = false; }
static void frame_u8(frame_t *f, uint8_t v)   { s_tx_workspace.data[f->pos++] = v; }
static void frame_u16(frame_t *f, uint16_t v) { frame_u8(f, v>>8); frame_u8(f, v&0xFF); }
static void __attribute__((unused)) frame_u32(frame_t *f, uint32_t v)
{
    frame_u8(f, (v>>24)&0xFF); frame_u8(f, (v>>16)&0xFF);
    frame_u8(f, (v>>8)&0xFF);  frame_u8(f, v&0xFF);
}
static void frame_bytes(frame_t *f, const uint8_t *d, uint16_t n)
{
    memcpy(&s_tx_workspace.data[f->pos], d, n); f->pos += n;
}

static uint8_t checksum(const uint8_t *data, uint16_t len)
{
    uint8_t cs = 0;
    for (uint16_t i = 0; i < len; i++) cs ^= data[i];
    return cs;
}

static int send_frame_channel(frame_t *body, uint8_t channel);
static int send_frame_channel_delivered(frame_t *body, uint8_t channel);
static bool build_header(frame_t *f, uint16_t msg_id, uint16_t body_len);

static int send_terminal_info_to(uint8_t channel)
{
    uint8_t body[JT808_TERMINAL_INFO_BODY_LENGTH];
    uint16_t length;
    frame_t frame;
    int send_result;
    jt808_terminal_info_result_t encode_result =
        jt808_terminal_info_encode(body, sizeof(body), &length);
    if (encode_result != JT808_TERMINAL_INFO_OK) {
        dbg_printf("[808] ch%u 0x0107 unavailable reason=%u\r\n",
                   channel, (unsigned)encode_result);
        return -1;
    }
    if (!frame_init(&frame)) return -1;
    if (!build_header(&frame, 0x0107U, length)) {
        frame_release();
        return -1;
    }
    frame_bytes(&frame, body, length);
    send_result = send_frame_channel_delivered(&frame, channel);
    frame_release();
    return send_result;
}

static void queue_boot_terminal_info(uint8_t channel)
{
    boot_terminal_info_t *state = channel == TCP_CH_MAIN ?
                                  &s_boot_terminal_info[0] :
                                  channel == TCP_CH_BACKUP ?
                                  &s_boot_terminal_info[1] : NULL;
    if (state == NULL || state->sent || state->pending) return;
    state->pending = true;
    state->attempts = 0U;
    state->retry_at_ms = TICK_MS();
}

static void process_boot_terminal_info(uint32_t now)
{
    static const uint8_t channels[2] = { TCP_CH_MAIN, TCP_CH_BACKUP };
    uint8_t index;
    for (index = 0U; index < 2U; ++index) {
        boot_terminal_info_t *state = &s_boot_terminal_info[index];
        uint8_t channel = channels[index];
        if (!state->pending || state->sent || !jt808_channel_online(channel) ||
            (int32_t)(now - state->retry_at_ms) < 0)
            continue;
        if (send_terminal_info_to(channel) == 0) {
            state->pending = false;
            state->sent = true;
            state->attempts = 0U;
            dbg_printf("[808] ch%u 0x0107 boot attributes sent\r\n", channel);
            continue;
        }
        ++state->attempts;
        if (state->attempts >= JT808_TERMINAL_INFO_MAX_TRIES) {
            state->attempts = 0U;
            state->retry_at_ms = now + JT808_TERMINAL_INFO_BACKOFF_MS;
        } else {
            state->retry_at_ms = now + JT808_TERMINAL_INFO_RETRY_MS;
        }
    }
}

/* Escape + wrap in 0x7E and send */
static int send_frame_broadcast(frame_t *body, bool require_all)
{
    bool attempted = false;
    bool delivered = false;
    bool failed = false;
    if (jt808_channel_online(TCP_CH_MAIN)) {
        attempted = true;
        if (send_frame_channel_delivered(body, TCP_CH_MAIN) == 0)
            delivered = true;
        else
            failed = true;
    }
    if (jt808_channel_online(TCP_CH_BACKUP)) {
        attempted = true;
        if (send_frame_channel_delivered(body, TCP_CH_BACKUP) == 0)
            delivered = true;
        else
            failed = true;
    }
    frame_release();
    if (!attempted || !delivered || (require_all && failed)) return -1;
    return 0;
}

static int send_frame(frame_t *body)
{
    return send_frame_broadcast(body, false);
}

static int finish_frame_channel(frame_t *body, uint8_t channel)
{
    int result = send_frame_channel(body, channel);
    frame_release();
    return result;
}

static int send_frame_channel(frame_t *body, uint8_t channel)
{
    uint8_t *out = s_tx_workspace.data;
    uint16_t i, write;
    if (!tcp_manager_ch_online(channel)) {
        ec800m_tcp_send_clear_ambiguous();
        return -1;
    }
    if (!body->prepared) {
        uint8_t cs = checksum(out, body->pos);
        uint16_t escaped_len =
            (cs == FRAME_FLAG || cs == ESC_FLAG) ? 2U : 1U;
        for (i = 0U; i < body->pos; ++i) {
            escaped_len +=
                (out[i] == FRAME_FLAG || out[i] == ESC_FLAG) ? 2U : 1U;
        }
        if ((uint32_t)escaped_len + 2U > sizeof(s_tx_workspace.data)) {
            ec800m_tcp_send_clear_ambiguous();
            return -1;
        }
        write = escaped_len + 1U;
        out[write--] = FRAME_FLAG;
        if (cs == FRAME_FLAG || cs == ESC_FLAG) {
            out[write--] = cs == FRAME_FLAG ? 0x02U : 0x01U;
            out[write--] = ESC_FLAG;
        } else {
            out[write--] = cs;
        }
        for (i = body->pos; i > 0U; --i) {
            uint8_t b = out[i - 1U];
            if (b == FRAME_FLAG || b == ESC_FLAG) {
                out[write--] = b == FRAME_FLAG ? 0x02U : 0x01U;
                out[write--] = ESC_FLAG;
            } else {
                out[write--] = b;
            }
        }
        out[0] = FRAME_FLAG;
        body->wire_len = (uint16_t)(escaped_len + 2U);
        body->prepared = true;
    }
    return ec800m_tcp_send(channel, out, body->wire_len);
}

static int send_frame_channel_delivered(frame_t *body, uint8_t channel)
{
    int result = send_frame_channel(body, channel);
    if (result == 0 || ec800m_tcp_send_was_ambiguous()) return 0;
    return result;
}

/* Build standard JT808 header */
static bool build_header(frame_t *f, uint16_t msg_id, uint16_t body_len)
{
    char pid[12];
    char phone[13];
    char terminal_id[8];
    uint8_t phone_bcd[6];

    if (!terminal_identity_sync(pid, phone, terminal_id) ||
        !terminal_identity_encode_phone(pid, phone_bcd))
        return false;
    memcpy(s_term.terminal_id, terminal_id, sizeof(s_term.terminal_id));
    frame_u16(f, msg_id);
    frame_u16(f, body_len & 0x03FF);   /* no fragmentation flag */
    frame_bytes(f, phone_bcd, 6);
    frame_u16(f, ++s_msg_sn);
    return true;
}

static bool refresh_terminal_identity(void)
{
    char pid[12], phone[13], terminal_id[8];
    if (!terminal_identity_sync(pid, phone, terminal_id)) return false;
    memcpy(s_term.terminal_id, terminal_id, sizeof(s_term.terminal_id));
    s_boot_identity_source = terminal_identity_last_result();
    return true;
}

static void log_boot_identity(void)
{
    if (!s_boot_identity_logged) {
        char imei[16] = {0};
        char iccid[24] = {0};
        device_config_t *config = cfg_get();
        if (config == NULL) return;
        ec800m_get_imei(imei, sizeof(imei));
        ec800m_get_iccid(iccid, sizeof(iccid));
        dbg_printf("[DEVICE] IMEI=%s ICCID=%s DEVICE_ID=%s JT808_TID=%s PID_SOURCE=%s\r\n",
                   imei, iccid, config->pid, s_term.terminal_id,
                   terminal_identity_result_name(s_boot_identity_source));
        if (config->backup_ip[0] == '\0' || config->backup_port == 0U) {
            dbg_printf("[SERVER] MAIN=%s:%u BACKUP=OFF\r\n",
                       config->server_ip, (unsigned)config->server_port);
        } else {
            dbg_printf("[SERVER] MAIN=%s:%u BACKUP=%s:%u\r\n",
                       config->server_ip, (unsigned)config->server_port,
                       config->backup_ip, (unsigned)config->backup_port);
        }
        s_boot_identity_logged = true;
    }
}

static void log_identity_invalid(uint32_t now,
                                 terminal_identity_result_t reason)
{
    if (!s_identity_logged || now - s_identity_log_ms >= 5000U) {
        dbg_printf("[808] identity invalid reason=%s\r\n",
                   terminal_identity_result_name(reason));
        s_identity_log_ms = now;
        s_identity_logged = true;
    }
}

static void identity_valid(void)
{
    s_identity_logged = false;
}

/* ── Message builders ─────────────────────────────────────────────────────── */
uint8_t jt808_encode_plate_gbk(const char *plate, uint8_t *out,
                                uint8_t capacity)
{
    typedef struct {
        uint8_t utf8[3];
        uint8_t gbk[2];
    } province_encoding_t;
    static const province_encoding_t provinces[] = {
        {{0xe4U, 0xbaU, 0xacU}, {0xbeU, 0xa9U}},
        {{0xe6U, 0xb5U, 0x99U}, {0xd5U, 0xe3U}},
        {{0xe6U, 0xb4U, 0xa5U}, {0xbdU, 0xf2U}},
        {{0xe7U, 0x9aU, 0x96U}, {0xcdU, 0xeeU}},
        {{0xe6U, 0xb2U, 0xaaU}, {0xbbU, 0xa6U}},
        {{0xe9U, 0x97U, 0xbdU}, {0xc3U, 0xf6U}},
        {{0xe6U, 0xb8U, 0x9dU}, {0xd3U, 0xe5U}},
        {{0xe8U, 0xb5U, 0xa3U}, {0xb8U, 0xd3U}},
        {{0xe6U, 0xb8U, 0xafU}, {0xb8U, 0xdbU}},
        {{0xe9U, 0xb2U, 0x81U}, {0xc2U, 0xb3U}},
        {{0xe6U, 0xbeU, 0xb3U}, {0xb0U, 0xc4U}},
        {{0xe8U, 0xb1U, 0xabU}, {0xd4U, 0xa5U}},
        {{0xe8U, 0x92U, 0x99U}, {0xc3U, 0xc9U}},
        {{0xe9U, 0x84U, 0x82U}, {0xb6U, 0xf5U}},
        {{0xe6U, 0x96U, 0xb0U}, {0xd0U, 0xc2U}},
        {{0xe6U, 0xb9U, 0x98U}, {0xcfU, 0xe6U}},
        {{0xe5U, 0xaeU, 0x81U}, {0xc4U, 0xfeU}},
        {{0xe7U, 0xb2U, 0xa4U}, {0xd4U, 0xc1U}},
        {{0xe8U, 0x97U, 0x8fU}, {0xb2U, 0xd8U}},
        {{0xe7U, 0x90U, 0xbcU}, {0xc7U, 0xedU}},
        {{0xe6U, 0xa1U, 0x82U}, {0xb9U, 0xf0U}},
        {{0xe5U, 0xb7U, 0x9dU}, {0xb4U, 0xa8U}},
        {{0xe8U, 0x9cU, 0x80U}, {0xcaU, 0xf1U}},
        {{0xe5U, 0x86U, 0x80U}, {0xbcU, 0xbdU}},
        {{0xe8U, 0xb4U, 0xb5U}, {0xb9U, 0xf3U}},
        {{0xe9U, 0xbbU, 0x94U}, {0xc7U, 0xadU}},
        {{0xe6U, 0x99U, 0x8bU}, {0xbdU, 0xfaU}},
        {{0xe4U, 0xbaU, 0x91U}, {0xd4U, 0xc6U}},
        {{0xe6U, 0xbbU, 0x87U}, {0xb5U, 0xe1U}},
        {{0xe8U, 0xbeU, 0xbdU}, {0xc1U, 0xc9U}},
        {{0xe9U, 0x99U, 0x95U}, {0xc9U, 0xc2U}},
        {{0xe7U, 0xa7U, 0xa6U}, {0xc7U, 0xd8U}},
        {{0xe5U, 0x90U, 0x89U}, {0xbcU, 0xaaU}},
        {{0xe7U, 0x94U, 0x98U}, {0xb8U, 0xcaU}},
        {{0xe9U, 0x99U, 0x87U}, {0xc2U, 0xa4U}},
        {{0xe9U, 0xbbU, 0x91U}, {0xbaU, 0xdaU}},
        {{0xe9U, 0x9dU, 0x92U}, {0xc7U, 0xe0U}},
        {{0xe8U, 0x8bU, 0x8fU}, {0xcbU, 0xd5U}},
        {{0xe5U, 0x8fU, 0xb0U}, {0xccU, 0xa8U}},
    };
    size_t length = strlen(plate);
    size_t i;


    if (length >= 3U) {
        for (i = 0U; i < sizeof(provinces) / sizeof(provinces[0]); ++i) {
            if (memcmp(plate, provinces[i].utf8, 3U) == 0) {
                size_t suffix_length = length - 3U;
                if (suffix_length + 2U > capacity) return 0U;
                memcpy(out, provinces[i].gbk, 2U);
                memcpy(out + 2U, plate + 3U, suffix_length);
                return (uint8_t)(suffix_length + 2U);
            }
        }
    }
    if (length > capacity) return 0U;
    memcpy(out, plate, length);
    return (uint8_t)length;
}

static int send_register_current_identity(uint8_t channel)
{
    /* body: province(2)+city(2)+manuf(5)+model(20)+term_id(7)+color(1)+plate
     * 808-2013 Table 7: 终端型号 BYTE[20], 终端ID BYTE[7] */
    uint8_t model[20] = {0}, tid[7] = {0}, plate[CFG_PLATE_LEN] = {0};
    uint8_t plate_length = jt808_encode_plate_gbk(s_term.plate_no, plate,
                                             sizeof(plate));
    memcpy(model, s_term.terminal_model,
           strlen(s_term.terminal_model) < 20 ? strlen(s_term.terminal_model) : 20);
    memcpy(tid,   s_term.terminal_id,
           strlen(s_term.terminal_id)    < 7 ? strlen(s_term.terminal_id)    : 7);

    uint8_t body[128];
    uint16_t pos = 0;
    const device_config_t *config = cfg_get();
    memcpy(&body[pos], config->province_be, 2U); pos += 2U;
    memcpy(&body[pos], config->city_be, 2U); pos += 2U;
    memcpy(&body[pos], s_term.manufacturer_id, 5); pos += 5;
    memcpy(&body[pos], model, 20);             pos += 20;
    memcpy(&body[pos], tid,   7);              pos += 7;
    body[pos++] = config->plate_color_valid == 1U ? config->plate_color : s_term.color;
    memcpy(&body[pos], plate, plate_length); pos += plate_length;

    frame_t f;
    if (!frame_init(&f)) {
        jt808_session_t *session = session_for_channel(channel);
        if (session != NULL)
            jt808_session_mark_send_failed(session, JT808_ACTION_REGISTER,
                                           TICK_MS());
        return -1;
    }
    if (!build_header(&f, MSG_TERMINAL_REGISTER, pos)) {
        frame_release();
        jt808_session_t *session = session_for_channel(channel);
        if (session != NULL)
            jt808_session_mark_send_failed(session, JT808_ACTION_REGISTER,
                                           TICK_MS());
        return -1;
    }
    frame_bytes(&f, body, pos);
    {
        jt808_session_t *session = session_for_channel(channel);
        int result = finish_frame_channel(&f, channel);
        if (result == 0) {
            if (session != NULL) {
                jt808_session_mark_sent(session, JT808_ACTION_REGISTER,
                                        s_msg_sn, TICK_MS());
                dbg_printf("[808] ch%u %s sent attempt=%u\r\n",
                           channel, jt808_action_name(JT808_ACTION_REGISTER),
                           (unsigned)session->attempts);
            }
        } else if (session != NULL) {
            if (ec800m_tcp_send_was_ambiguous()) {
                /* "SEND OK" wasn't observed, but the frame was already on
                 * the wire, so book it as sent (not failed): pending_serial
                 * tracks the serial that actually went out, so a late
                 * genuine ACK is still accepted, and the normal retry/
                 * backoff timers still apply if it truly was lost (see the
                 * ambiguous-timeout precedent in the main dispatch loop). */
                jt808_session_mark_sent(session, JT808_ACTION_REGISTER,
                                        s_msg_sn, TICK_MS());
                dbg_printf("[808] ch%u %s ambiguous attempt=%u\r\n",
                           channel, jt808_action_name(JT808_ACTION_REGISTER),
                           (unsigned)session->attempts);
            } else {
                jt808_session_mark_send_failed(session,
                                               JT808_ACTION_REGISTER,
                                               TICK_MS());
                dbg_printf("[808] ch%u %s fail attempt=%u backoff=%lu\r\n",
                           channel, jt808_action_name(JT808_ACTION_REGISTER),
                           (unsigned)session->attempts,
                           (unsigned long)session->backoff_until_ms);
            }
        }
        return result;
    }
}

int jt808_send_register_to(uint8_t channel)
{
    if (session_for_channel(channel) == NULL) return -1;
    if (!refresh_terminal_identity()) return -1;
    return send_register_current_identity(channel);
}

void jt808_request_reregister(void)
{
    s_cfg.auth_code[0] = '\0';
    s_cfg.backup_auth_code[0] = '\0';
    (void)cfg_set_auth_code(TCP_CH_MAIN, "");
    (void)cfg_set_auth_code(TCP_CH_BACKUP, "");
    jt808_session_init(&s_sessions[0], TCP_CH_MAIN);
    jt808_session_init(&s_sessions[1], TCP_CH_BACKUP);
    memset(s_pending_auth, 0, sizeof(s_pending_auth));
    s_term.terminal_id[0] = '\0';
}

int jt808_send_auth_to(uint8_t channel, const char *code)
{
    jt808_session_t *session = session_for_channel(channel);
    uint8_t len;
    int result;
    if (session == NULL || code == NULL) return -1;
    len = (uint8_t)strlen(code);
    frame_t f;
    if (!frame_init(&f)) {
        jt808_session_mark_send_failed(session, JT808_ACTION_AUTH, TICK_MS());
        return -1;
    }
    if (!build_header(&f, MSG_TERMINAL_AUTH, len)) {
        frame_release();
        jt808_session_mark_send_failed(session, JT808_ACTION_AUTH, TICK_MS());
        return -1;
    }
    frame_bytes(&f, (const uint8_t *)code, len);
    result = finish_frame_channel(&f, channel);
    if (result == 0) {
        jt808_session_mark_sent(session, JT808_ACTION_AUTH, s_msg_sn, TICK_MS());
        dbg_printf("[808] ch%u %s sent attempt=%u\r\n",
                   channel, jt808_action_name(JT808_ACTION_AUTH),
                   (unsigned)session->attempts);
    } else if (ec800m_tcp_send_was_ambiguous()) {
        /* Bytes were already on the wire; book it as sent so pending_serial
         * tracks this attempt and a late genuine ACK is still accepted. */
        jt808_session_mark_sent(session, JT808_ACTION_AUTH, s_msg_sn, TICK_MS());
        dbg_printf("[808] ch%u %s ambiguous attempt=%u\r\n",
                   channel, jt808_action_name(JT808_ACTION_AUTH),
                   (unsigned)session->attempts);
    } else {
        jt808_session_mark_send_failed(session, JT808_ACTION_AUTH, TICK_MS());
        dbg_printf("[808] ch%u %s fail attempt=%u backoff=%lu\r\n",
                   channel, jt808_action_name(JT808_ACTION_AUTH),
                   (unsigned)session->attempts,
                   (unsigned long)session->backoff_until_ms);
    }
    return result;
}

int jt808_send_heartbeat(void)
{
    frame_t f; if (!frame_init(&f)) return -1;
    if (!build_header(&f, MSG_HEARTBEAT, 0)) { frame_release(); return -1; }
    return send_frame(&f);
}

void jt808_set_logical_acc(bool on)
{
    s_logical_acc_on = on;
    s_logical_acc_override_set = true;
}

bool jt808_get_logical_acc(void)
{
    if (s_logical_acc_override_set) return s_logical_acc_on;
    return hw_acc_is_on();
}

bool jt808_location_snapshot_valid(const gps_data_t *gps, uint32_t now)
{
    static const uint8_t days_in_month[13] =
        { 0U,31U,28U,31U,30U,31U,30U,31U,31U,30U,31U,30U,31U };
    uint8_t maximum_day;
    bool leap;

    if (gps == NULL || !gps->valid || gps->fix_quality == 0U ||
        (uint32_t)(now - gps->last_update_ms) > 5000U ||
        gps->year < 2000U || gps->month < 1U || gps->month > 12U ||
        gps->hour > 23U || gps->minute > 59U || gps->second > 59U)
        return false;
    leap = (gps->year % 4U == 0U && gps->year % 100U != 0U) ||
           (gps->year % 400U == 0U);
    maximum_day = gps->month == 2U && leap ? 29U : days_in_month[gps->month];
    return gps->day >= 1U && gps->day <= maximum_day;
}

void jt808_reset_endpoint_auth(uint8_t channel_mask)
{
    if ((channel_mask & JT808_ENDPOINT_MAIN_MASK) != 0U) {
        s_cfg.auth_code[0] = '\0';
        memset(&s_pending_auth[0], 0, sizeof(s_pending_auth[0]));
        jt808_session_init(&s_sessions[0], TCP_CH_MAIN);
    }
    if ((channel_mask & JT808_ENDPOINT_BACKUP_MASK) != 0U) {
        s_cfg.backup_auth_code[0] = '\0';
        memset(&s_pending_auth[1], 0, sizeof(s_pending_auth[1]));
        jt808_session_init(&s_sessions[1], TCP_CH_BACKUP);
    }
}

static uint8_t jt808_days_in_month(uint16_t year, uint8_t month)
{
    static const uint8_t days[13] =
        { 0U,31U,28U,31U,30U,31U,30U,31U,31U,30U,31U,30U,31U };
    bool leap = (year % 4U == 0U && year % 100U != 0U) ||
                (year % 400U == 0U);
    return month == 2U && leap ? 29U : days[month];
}

static void jt808_apply_timezone(const gps_data_t *gps,
                                 uint16_t *year, uint8_t *month,
                                 uint8_t *day, uint8_t *hour,
                                 uint8_t *minute)
{
    const device_config_t *config = cfg_get();
    int8_t sign = config->gmt_sign;
    uint8_t offset_hour = config->gmt_hour;
    uint8_t offset_minute = config->gmt_min;
    int32_t local_minutes;

    if ((sign != 1 && sign != -1) || offset_hour > 12U ||
        offset_minute > 59U) {
        sign = 1;
        offset_hour = 8U;
        offset_minute = 0U;
    }

    *year = gps->year;
    *month = gps->month;
    *day = gps->day;
    local_minutes = (int32_t)gps->hour * 60 + gps->minute +
                    (int32_t)sign *
                    ((int32_t)offset_hour * 60 + offset_minute);

    while (local_minutes < 0) {
        local_minutes += 24 * 60;
        if (*day > 1U) {
            --*day;
        } else {
            if (*month > 1U) {
                --*month;
            } else {
                *month = 12U;
                --*year;
            }
            *day = jt808_days_in_month(*year, *month);
        }
    }
    while (local_minutes >= 24 * 60) {
        local_minutes -= 24 * 60;
        if (*day < jt808_days_in_month(*year, *month)) {
            ++*day;
        } else {
            *day = 1U;
            if (*month < 12U) {
                ++*month;
            } else {
                *month = 1U;
                ++*year;
            }
        }
    }
    *hour = (uint8_t)(local_minutes / 60);
    *minute = (uint8_t)(local_minutes % 60);
}

static uint16_t encode_location_compact(const gps_data_t *g,
                                        uint8_t body[BLIND_ZONE_LOCATION_MAX])
{
    uint32_t alm = s_alarm_flags;
    uint32_t status = 0;

    /* PA12 M_ACC_IN is inverted by Q9: low collector means external ACC ON. */
    if (hw_acc_is_on())
        status |= LOC_FLAG_ACC_ON;
    /* 808-2013: bit2=1表示西经(默认东经不置位), bit3=1表示南纬(默认北纬不置位) */
    if (g->lon < 0) status |= LOC_FLAG_WEST_LON;
    if (g->lat < 0) status |= LOC_FLAG_SOUTH_LAT;
    if (g->fix_quality > 0)
        status |= LOC_FLAG_GPS_FIXED | LOC_FLAG_BEIDOU_FIXED;

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
    uint8_t t_hour;
    uint8_t t_minute;
    uint8_t t_day   = g->day;
    uint8_t t_month = g->month;
    uint16_t t_year = g->year;
    jt808_apply_timezone(g, &t_year, &t_month, &t_day, &t_hour, &t_minute);
    /* BCD time: YY MM DD HH mm SS in the configured local timezone. */
    body[p++] = (uint8_t)(((t_year%100)/10)<<4 | (t_year%10));
    body[p++] = (uint8_t)((t_month/10)<<4  | (t_month%10));
    body[p++] = (uint8_t)((t_day/10)<<4    | (t_day%10));
    body[p++] = (uint8_t)((t_hour/10)<<4   | (t_hour%10));
    body[p++] = (uint8_t)((t_minute/10)<<4 | (t_minute%10));
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

static uint16_t clamp_voltage_units(float volts, float units_per_volt)
{
    float scaled;
    if (!(volts > 0.0f)) return 0U;
    scaled = volts * units_per_volt;
    if (!(scaled < 65535.0f)) return 65535U;
    return (uint16_t)scaled;
}

static uint16_t coordinate_extension_tail(double coordinate)
{
    double magnitude = fabs(coordinate);
    uint32_t degrees;
    double low_scaled;
    if (!(magnitude <= 180.0)) return 0U;
    degrees = (uint32_t)magnitude;
    low_scaled = magnitude * 1000000000.0 -
                 (double)degrees * 1000000000.0;
    return (uint16_t)(((uint32_t)low_scaled) % 1000U);
}

static uint16_t altitude_extension_tail(float altitude)
{
    double scaled = fabs((double)altitude) * 1000.0;
    if (!(scaled < 4294967296.0)) return 0U;
    return (uint16_t)(((uint32_t)scaled) % 1000U);
}

static uint16_t encode_location_online(const gps_data_t *g,
                                       uint8_t body[JT808_LOCATION_ONLINE_MAX],
                                       uint32_t alarm_bits,
                                       bool historical_position)
{
    uint16_t p = encode_location_compact(g, body);
    uint32_t status = ((uint32_t)body[4] << 24) |
                      ((uint32_t)body[5] << 16) |
                      ((uint32_t)body[6] << 8) |
                      (uint32_t)body[7];
    uint32_t odometer = cfg_get()->mileage_m / 100U;
    uint16_t speed = g->speed_kmh <= 0.0f ? 0U :
                     g->speed_kmh >= 6553.5f ? 65535U :
                     (uint16_t)(g->speed_kmh * 10.0f);
    uint16_t car_001v = clamp_voltage_units(adc_get_car_voltage(), 100.0f);
    uint16_t bat_mv = clamp_voltage_units(adc_get_bat_voltage(), 1000.0f);
    uint16_t bat_01v = (uint16_t)(bat_mv / 100U);
    uint16_t bat_pct = bat_mv <= 3300U ? 0U : bat_mv >= 4200U ? 100U :
        (uint16_t)(((uint32_t)(bat_mv - 3300U) * 100U) / 900U);
    uint16_t lat_tail = coordinate_extension_tail(g->lat);
    uint16_t lon_tail = coordinate_extension_tail(g->lon);
    uint16_t alt_tail = altitude_extension_tail(g->altitude_m);
    uint16_t hdop_x10 = g->hdop <= 0.0f ? 0U :
                        g->hdop >= 99.9f ? 999U :
                        (uint16_t)(g->hdop * 10.0f + 0.5f);

    body[0]=(uint8_t)(alarm_bits>>24); body[1]=(uint8_t)(alarm_bits>>16);
    body[2]=(uint8_t)(alarm_bits>>8); body[3]=(uint8_t)alarm_bits;
    if (jt808_get_logical_acc()) status |= LOC_FLAG_ACC_ON;
    else status &= ~LOC_FLAG_ACC_ON;
    if (historical_position)
        status &= ~LOC_FLAG_GPS_FIXED;
    body[4]=(uint8_t)(status>>24); body[5]=(uint8_t)(status>>16);
    body[6]=(uint8_t)(status>>8); body[7]=(uint8_t)status;

    /* Replace the compact 0x31/0x30 suffix with the complete online profile. */
    p = 28U;
    body[p++]=0x01U; body[p++]=0x04U;
    body[p++]=(uint8_t)(odometer>>24); body[p++]=(uint8_t)(odometer>>16);
    body[p++]=(uint8_t)(odometer>>8); body[p++]=(uint8_t)odometer;
    body[p++]=0x03U; body[p++]=0x02U;
    body[p++]=(uint8_t)(speed>>8); body[p++]=(uint8_t)speed;
    body[p++]=0x30U; body[p++]=0x01U; body[p++]=(uint8_t)ec800m_get_csq();
    body[p++]=0x31U; body[p++]=0x01U; body[p++]=g->satellites;
    body[p++]=0x61U; body[p++]=0x02U;
    body[p++]=(uint8_t)(car_001v>>8); body[p++]=(uint8_t)car_001v;
    body[p++]=0xECU; body[p++]=0x05U;
    body[p++]=(uint8_t)(bat_pct>>8); body[p++]=(uint8_t)bat_pct;
    body[p++]=(uint8_t)(bat_01v>>8); body[p++]=(uint8_t)bat_01v;
    body[p++]=(uint8_t)(car_001v >= 550U ? 0U : 1U);
    body[p++]=0xE3U; body[p++]=0x0AU;
    body[p++]=(uint8_t)(lat_tail>>8); body[p++]=(uint8_t)lat_tail;
    body[p++]=(uint8_t)(lon_tail>>8); body[p++]=(uint8_t)lon_tail;
    body[p++]=(uint8_t)(alt_tail>>8); body[p++]=(uint8_t)alt_tail;
    body[p++]=g->fix_quality; body[p++]=g->satellites;
    body[p++]=(uint8_t)(hdop_x10>>8); body[p++]=(uint8_t)hdop_x10;
    return p;
}

int jt808_send_location_to(uint8_t channel, const gps_data_t *snapshot)
{
    uint8_t body[JT808_LOCATION_ONLINE_MAX];
    frame_t frame;
    uint16_t length;
    int result;
    if (!jt808_channel_online(channel) ||
        !jt808_location_snapshot_valid(snapshot, TICK_MS()))
        return -1;
    length = encode_location_online(snapshot, body, s_alarm_flags, false);
    if (!frame_init(&frame)) return -1;
    if (!build_header(&frame, MSG_LOCATION_REPORT, length)) { frame_release(); return -1; }
    frame_bytes(&frame, body, length);
    result = send_frame_channel_delivered(&frame, channel);
    frame_release();
    return result;
}

int jt808_send_location(void)
{
    blind_zone_record_t record;
    uint8_t online_body[JT808_LOCATION_ONLINE_MAX];
    frame_t f;
    int result = -1;
    gps_data_t snapshot = *gps_get_data();
    bool sent = false;

    if (s_append_pending) {
        blind_zone_result_t stored = blind_zone_append(&s_append_pending_record);
        if (stored == BLIND_ZONE_OK) {
            s_append_pending = false;
            s_alarm_flags = 0;
            return 0;
        }
        return -2;
    }

    if (!jt808_location_snapshot_valid(&snapshot, TICK_MS())) return -1;
    record.length = (uint8_t)encode_location_compact(&snapshot, record.location);
    if (!frame_init(&f)) return -1;
    {
        uint16_t online_length = encode_location_online(&snapshot, online_body,
                                                         s_alarm_flags, false);
        if (!build_header(&f, MSG_LOCATION_REPORT, online_length)) { frame_release(); return -1; }
        frame_bytes(&f, online_body, online_length);
    }
    if (jt808_channel_online(TCP_CH_MAIN) &&
        send_frame_channel_delivered(&f, TCP_CH_MAIN) == 0) sent = true;
    if (jt808_channel_online(TCP_CH_BACKUP) &&
        send_frame_channel_delivered(&f, TCP_CH_BACKUP) == 0) sent = true;
    frame_release();
    if (sent) {
        s_alarm_flags = 0;
        return 0;
    }

    {
        blind_zone_result_t stored = blind_zone_append(&record);
        if (stored == BLIND_ZONE_OK) {
            s_alarm_flags = 0;
            return 0;
        }
        if (stored == BLIND_ZONE_PENDING || stored == BLIND_ZONE_BUSY ||
            stored == BLIND_ZONE_IO_ERROR) {
            s_append_pending_record = record;
            s_append_pending = true;
            return -2;
        }
    }
    return result;
}

/* Rate-limit the "cannot build a location yet" notice.  Before boot GNSS has
 * no fix and nothing has ever been captured, so this condition can hold for
 * minutes; logging every attempt drowned the rest of the log and, because the
 * debug UART blocks, slowed the main loop that would eventually clear it. */
static void log_location_unavailable(const char *reason)
{
    static const char *last_reason;
    static uint32_t last_log_ms;
    static uint32_t suppressed;
    uint32_t now = TICK_MS();

    if (reason != last_reason ||
        (uint32_t)(now - last_log_ms) >= JT808_LOCATION_DROP_LOG_MS) {
        if (suppressed != 0U) {
            dbg_printf("[808] 0200 unavailable reason=%s (+%lu suppressed)\r\n",
                       reason, (unsigned long)suppressed);
        } else {
            dbg_printf("[808] 0200 unavailable reason=%s\r\n", reason);
        }
        last_reason = reason;
        last_log_ms = now;
        suppressed = 0U;
        return;
    }
    ++suppressed;
}

int jt808_send_location_work_mode(uint32_t alarm_bits,
                                  bool historical_position)
{
    uint8_t body[JT808_LOCATION_ONLINE_MAX];
    frame_t frame;
    gps_data_t snapshot;
    uint16_t length;
    int result;

    if (!jt808_is_online()) return -1;
    if (historical_position) {
        /* GNSS is off in STOP1.  Use only a snapshot captured while a live
         * fix was fresh; never encode the now-invalid live GPS object. */
        if (!gps_get_last_trusted(&snapshot)) {
            log_location_unavailable("no-trusted-fix");
            return JT808_SEND_NO_POSITION;
        }
    } else {
        snapshot = *gps_get_data();
        if (!jt808_location_snapshot_valid(&snapshot, TICK_MS())) {
            /* A live fix is not available yet -- GNSS was powered down in
             * STOP1 and has not re-acquired.  Dropping the frame here used to
             * lose ACC state changes and the whole stationary reporting
             * cadence until the receiver came back, so fall back to the
             * retained fix and mark the report historical instead. */
            if (!gps_get_last_trusted(&snapshot)) {
                log_location_unavailable("no-fix-no-trusted");
                return JT808_SEND_NO_POSITION;
            }
            historical_position = true;
            dbg_printf("[808] 0200 fallback=last-trusted\r\n");
        }
    }
    trial_discard_trace("[808] 0200 acc=%u alarm=0x%08lx hist=%u\r\n",
               (unsigned)jt808_get_logical_acc(),
               (unsigned long)alarm_bits, (unsigned)historical_position);
    length = encode_location_online(&snapshot, body, alarm_bits, historical_position);
    if (!frame_init(&frame)) return -1;
    if (!build_header(&frame, MSG_LOCATION_REPORT, length)) {
        frame_release();
        return -1;
    }
    frame_bytes(&frame, body, length);
    result = send_frame_broadcast(&frame, alarm_bits != 0U);
    if (result == 0) {
        s_last_location_ms = TICK_MS();
        s_alarm_flags &= ~alarm_bits;
    }
    return result;
}

void jt808_set_terminal_profile(const char *model, const char *plate)
{
    if (model != NULL) {
        strncpy(s_term.terminal_model, model, sizeof(s_term.terminal_model) - 1U);
        s_term.terminal_model[sizeof(s_term.terminal_model) - 1U] = '\0';
    }
    if (plate != NULL) {
        strncpy(s_term.plate_no, plate, sizeof(s_term.plate_no) - 1U);
        s_term.plate_no[sizeof(s_term.plate_no) - 1U] = '\0';
    }
}

static int send_location_only(uint16_t message_id)
{
    uint8_t body[JT808_LOCATION_ONLINE_MAX];
    frame_t frame;
    gps_data_t snapshot = *gps_get_data();
    uint16_t length;
    if (!jt808_is_online()) return -1;
    if (!jt808_location_snapshot_valid(&snapshot, TICK_MS())) return -1;
    length = encode_location_online(&snapshot, body, s_alarm_flags, false);
    if (!frame_init(&frame)) return -1;
    if (!build_header(&frame, message_id, length)) { frame_release(); return -1; }
    frame_bytes(&frame, body, length);
    return finish_frame_channel(&frame, s_response_channel);
}

static void process_location_timer(uint32_t now)
{
    /* WORK_MODE_STATIONARY_SLEEP powers GNSS down.  In that state work_mode.c
     * is the only owner of 0x0200 scheduling: it emits the sleep-entry report
     * and any configured retained-position cadence.  Letting this legacy
     * live-GNSS timer continue turns its stale-fix fallback into a continuous
     * stream of duplicate historical locations. */
    if (work_mode_state() == WORK_MODE_STATIONARY_SLEEP) {
        gps_data_t first_snapshot = *gps_get_data();
        uint8_t first_index;
        bool first_sent = false;

        if (jt808_location_snapshot_valid(&first_snapshot, now)) {
            for (first_index = 0U; first_index < 2U; ++first_index) {
                jt808_session_t *session = &s_sessions[first_index];
                if (session->waiting_first_fix &&
                    jt808_channel_online(session->channel) &&
                    jt808_send_location_to(session->channel,
                                           &first_snapshot) == 0) {
                    session->waiting_first_fix = false;
                    first_sent = true;
                }
            }
            if (first_sent) s_last_location_ms = now;
        }
        return;
    }

    gps_data_t snapshot = *gps_get_data();
    bool valid = jt808_location_snapshot_valid(&snapshot, now);
    uint8_t index;
    bool first_fix_sent = false;
    bool corner_append_blocked = false;

    /* Retry a deferred corner blind-zone append regardless of whether a new
     * heading sample/event arrived this tick. */
    if (s_corner_append_pending) {
        blind_zone_result_t stored = blind_zone_append(&s_corner_pending_record);
        if (stored == BLIND_ZONE_OK) {
            if (motion_corner_peek_candidate != NULL &&
                motion_corner_consume_candidate != NULL) {
                motion_corner_candidate_t pending;
                if (motion_corner_peek_candidate(&s_motion_corner, &pending) &&
                    pending.sample.sample_ms == s_corner_pending_candidate.sample.sample_ms)
                    motion_corner_consume_candidate(&s_motion_corner);
            }
            s_corner_append_pending = false;
            s_last_location_ms = now;
        }
        corner_append_blocked = s_corner_append_pending;
    }

    /* Feed the pure corner state machine only with fresh RMC heading samples.
     * GGA updates last_update_ms but never heading_update_ms. */
    {
        motion_corner_sample_t sample;
        motion_corner_event_t event;
        bool snapshot_slot_available = true;
        const gps_data_t *g = &snapshot;
        sample.heading_deg = g->heading;
        sample.speed_kmh = g->speed_kmh;
        sample.sample_ms = g->heading_update_ms;
        sample.valid = valid && cfg_get()->anglerep_en != 0U &&
                       g->speed_kmh >= (float)cfg_get()->anglerep_speed;
        sample.heading_fresh = sample.valid && g->heading_update_ms != 0U &&
                               g->heading_update_ms != s_corner_last_heading_ms &&
                               !corner_append_blocked;
        /* Keep a bounded lookup of the latest RMC snapshots.  Candidates are
         * metadata-only, so the snapshot must be retained independently until
         * the candidate is sent or handed off to blind-zone storage. */
        if (sample.heading_fresh) {
            uint8_t slot = 0U;
            uint8_t i;
            bool found = false;
            /* Prefer an unused slot; never evict a snapshot still referenced
             * by one of the three pending candidates. */
            for (i = 0U; i < MOTION_CORNER_CANDIDATE_CAPACITY; ++i) {
                bool referenced = false;
                uint8_t j;
                for (j = 0U; motion_corner_pending_candidates != NULL &&
                            j < motion_corner_pending_candidates(&s_motion_corner); ++j)
                    if (s_motion_corner.candidates[j].sample.sample_ms ==
                        s_corner_snapshot_ms[i]) referenced = true;
                if (!referenced) { slot = i; found = true; break; }
            }
            if (found) {
                s_corner_snapshots[slot] = snapshot;
                s_corner_snapshot_ms[slot] = sample.sample_ms;
                s_corner_last_heading_ms = sample.sample_ms;
            } else {
                snapshot_slot_available = false;
                s_corner_last_heading_ms = sample.sample_ms;
                sample.heading_fresh = false;
            }
        }
        (void)snapshot_slot_available;
        event = corner_step_safe(&s_motion_corner, &sample);
        if (event.report_due) {
            motion_corner_candidate_t candidate;
            gps_data_t cached = snapshot;
            bool have = motion_corner_peek_candidate != NULL &&
                        motion_corner_peek_candidate(&s_motion_corner, &candidate);
            if (have) {
                uint8_t i;
                for (i = 0U; i < MOTION_CORNER_CANDIDATE_CAPACITY; ++i)
                    if (s_corner_snapshot_ms[i] == candidate.sample.sample_ms) {
                        cached = s_corner_snapshots[i];
                        break;
                    }
            }
            if (have) {
                uint8_t body[JT808_LOCATION_ONLINE_MAX];
                frame_t frame;
                uint16_t length = encode_location_online(&cached, body,
                                                         s_alarm_flags, false);
                bool sent = false;
                if (frame_init(&frame)) {
                    if (build_header(&frame, MSG_LOCATION_REPORT, length)) {
                        frame_bytes(&frame, body, length);
                        if (jt808_channel_online(TCP_CH_MAIN) &&
                            send_frame_channel_delivered(&frame, TCP_CH_MAIN) == 0) sent = true;
                        if (jt808_channel_online(TCP_CH_BACKUP) &&
                            send_frame_channel_delivered(&frame, TCP_CH_BACKUP) == 0) sent = true;
                    }
                    frame_release();
                }
                if (sent) {
                    if (motion_corner_consume_candidate != NULL)
                        motion_corner_consume_candidate(&s_motion_corner);
                    s_last_location_ms = now;
                    s_alarm_flags = 0U;
                } else {
                    blind_zone_record_t record;
                    record.event_id = candidate.sample.sample_ms;
                    record.length = (uint8_t)encode_location_compact(&cached, record.location);
                    {
                        blind_zone_result_t stored = blind_zone_append(&record);
                        if (stored == BLIND_ZONE_OK) {
                            if (motion_corner_consume_candidate != NULL)
                                motion_corner_consume_candidate(&s_motion_corner);
                            s_last_location_ms = now;
                        } else if (stored == BLIND_ZONE_PENDING ||
                                   stored == BLIND_ZONE_BUSY ||
                                   stored == BLIND_ZONE_IO_ERROR) {
                            s_corner_pending_record = record;
                            s_corner_pending_candidate = candidate;
                            s_corner_append_pending = true;
                        }
                    }
                }
                return;
            }
            if (event.reason == MOTION_CORNER_REASON_TURN_EXIT) {
                /* Exit events may have no queued candidate; still emit the
                 * live point so the transition is observable. */
                if (jt808_send_location() == 0) s_last_location_ms = now;
                return;
            }
        }
    }

    if (valid) {
        for (index = 0U; index < 2U; ++index) {
            jt808_session_t *session = &s_sessions[index];
            if (session->waiting_first_fix &&
                jt808_channel_online(session->channel) &&
                jt808_send_location_to(session->channel, &snapshot) == 0) {
                session->waiting_first_fix = false;
                first_fix_sent = true;
            }
        }
        if (first_fix_sent) s_last_location_ms = now;
    }
}

int jt808_send_general_resp_to(uint8_t channel, uint16_t resp_sn,
                               uint16_t resp_id, uint8_t result)
{
    frame_t f; if (!frame_init(&f)) return -1;
    if (!build_header(&f, MSG_TERMINAL_GENERAL_RESP, 5)) { frame_release(); return -1; }
    frame_u16(&f, resp_sn);
    frame_u16(&f, resp_id);
    frame_u8(&f, result);
    return finish_frame_channel(&f, channel);
}

int jt808_send_general_resp(uint16_t resp_sn, uint16_t resp_id, uint8_t result)
{ return jt808_send_general_resp_to(s_response_channel, resp_sn, resp_id, result); }

/* Send an arbitrary message with a pre-built body (used by jt808_params.c).
 * resp_sn is currently unused (responses carry their own running serial). */
int jt808_send_raw(uint16_t msg_id, uint16_t resp_sn,
                   const uint8_t *body, uint16_t blen)
{
    (void)resp_sn;
    frame_t f; if (!frame_init(&f)) return -1;
    if (!build_header(&f, msg_id, blen)) { frame_release(); return -1; }
    if (blen) frame_bytes(&f, body, blen);
    return finish_frame_channel(&f, s_response_channel);
}

int jt808_send_raw_tracked(uint16_t msg_id, const uint8_t *body,
                           uint16_t blen, uint16_t *serial_out)
{
    frame_t f;
    if (serial_out == NULL || blen > 512U - 12U ||
        (blen != 0U && body == NULL))
        return -1;
    if (!frame_init(&f)) return -1;
    if (!build_header(&f, msg_id, blen)) { frame_release(); return -1; }
    *serial_out = s_msg_sn;
    if (blen != 0U) frame_bytes(&f, body, blen);
    if (!jt808_is_online()) { frame_release(); return -1; }
    return finish_frame_channel(&f, jt808_online_channel());
}

#if defined(__GNUC__)
/* Host contract harnesses link jt808.c without the command executor. The weak
 * default keeps them linking; the real at_config.c definition wins in the
 * firmware build. */
__attribute__((weak)) bool at_config_execute_text_command(const uint8_t *text,
                                                          uint16_t len)
{
    (void)text;
    (void)len;
    return false;
}
#endif

/* 0x8300 body: flag byte, then GBK text (spec table 37).  The terminal command
 * set is plain ASCII framed by a trailing '#', matching the SMS channel, so
 * the text is handed to the same executor.  Kept out of process_frame() so its
 * locals do not widen that function's audited stack frame. */
static bool __attribute__((noinline)) handle_text_message(const uint8_t *body,
                                                          uint16_t body_len)
{
    uint16_t text_len;

    if (body_len < 2U) return false;
    text_len = (uint16_t)(body_len - 1U);
    if (body[body_len - 1U] == (uint8_t)'#') --text_len;
    if (text_len == 0U) return false;
    return at_config_execute_text_command(&body[1], text_len);
}

/* ── RX frame parser ──────────────────────────────────────────────────────── */
static void __attribute__((noinline)) process_frame(
    uint8_t channel, uint32_t generation, uint8_t *frame, uint16_t raw_len)
{
    jt808_session_t *session = session_for_channel(channel);
    pending_auth_t *pending = pending_auth_for_channel(channel);
    /* Forward in-place unescape is safe because flen never exceeds i. */
    uint16_t flen = 0;
    bool escape_error = false;
    for (uint16_t i = 0; i < raw_len && flen < JT808_RX_MAX; i++) {
        if (frame[i] == ESC_FLAG && i + 1 < raw_len) {
            if (frame[i+1] == 0x01)      frame[flen++] = ESC_FLAG;
            else if (frame[i+1] == 0x02) frame[flen++] = FRAME_FLAG;
            else escape_error = true;
            i++;
        } else if (frame[i] == ESC_FLAG) {
            escape_error = true;
        } else {
            frame[flen++] = frame[i];
        }
    }
    if (escape_error) {
        dbg_printf("[808-RX] ch=%u drop=ESCAPE\r\n", channel);
        return;
    }
    if (session == NULL || flen < 13U) {
        dbg_printf("[808-RX] ch=%u drop=SHORT len=%u\r\n", channel, flen);
        return;  /* header(12) + checksum(1) */
    }

    /* Verify checksum */
    uint8_t cs = checksum(frame, flen - 1);
    if (cs != frame[flen - 1]) {
        dbg_printf("[808-RX] ch=%u drop=CHECKSUM\r\n", channel);
        return;
    }

    uint16_t msg_id     = ((uint16_t)frame[0] << 8) | frame[1];
    uint16_t body_prop  = ((uint16_t)frame[2] << 8) | frame[3];
    uint16_t body_len   = body_prop & 0x03FF;
    uint16_t serial_no  = ((uint16_t)frame[10] << 8) | frame[11];
    const uint8_t *body = &frame[12];
    if ((body_prop & 0x2000U) != 0U || body_len != flen - 13U) {
        dbg_printf("[808-RX] ch=%u drop=LENGTH body=%u frame=%u\r\n",
                   channel, body_len, (unsigned int)(flen - 13U));
        return;
    }
    trial_discard_trace("[808-RX] ch=%u msg=0x%04x sn=%u body=%u\r\n",
               channel, msg_id, serial_no, body_len);
    if (msg_id != MSG_TERMINAL_REGISTER_RESP &&
        msg_id != MSG_PLATFORM_GENERAL_RESP &&
        !jt808_channel_online(channel)) {
        dbg_printf("[808-RX] ch=%u drop=OFFLINE msg=0x%04x\r\n",
                   channel, msg_id);
        return;
    }

    switch (msg_id) {
    case MSG_PLATFORM_GENERAL_RESP:
        if (body_len == 5U) {
            uint16_t reply_serial = ((uint16_t)body[0] << 8) | body[1];
            uint16_t reply_msg_id = ((uint16_t)body[2] << 8) | body[3];
            if (jt808_channel_online(channel))
                blind_zone_replay_on_general_ack(channel, generation,
                                                  reply_serial, reply_msg_id, body[4]);
            if (reply_msg_id == MSG_TERMINAL_AUTH &&
                jt808_session_accept_auth(session, generation, reply_serial)) {
                if (body[4] == 0U) {
                    jt808_session_mark_online(session);
                    queue_boot_terminal_info(channel);
                    log_platform_on_first_online();
                    dbg_printf("[808] ch%u ONLINE\r\n", channel);
                } else {
                    if (jt808_session_reject_or_timeout(session, TICK_MS()))
                        clear_channel_auth(channel);
                    dbg_printf("[808] ch%u auth rejected result=%u\r\n",
                               channel, body[4]);
                }
            }
        }
        break;

    case MSG_TERMINAL_REGISTER_RESP:
        if (body_len >= 3U) {
            dbg_printf("[808-RX] ch=%u msg=0x%04x sn=%u result=%u\r\n",
                       channel, msg_id, serial_no, body[2]);
        }
        if (body_len >= 3U &&
            jt808_session_accept_register(
                session, generation,
                (uint16_t)(((uint16_t)body[0] << 8) | body[1]))) {
            uint8_t result = body[2];
            jt808_session_consume_register(session);
            dbg_printf("[808] ch%u REGISTER_RESP result=%u\r\n", channel, result);
            if (result == 0) {
                uint8_t code_len = (uint8_t)(body_len - 3U);
                if (pending == NULL || code_len == 0U ||
                    code_len >= sizeof(pending->code)) {
                    jt808_session_reject_or_timeout(session, TICK_MS());
                    break;
                }
                memcpy(pending->code, &body[3], code_len);
                pending->code[code_len] = '\0';
                pending->generation = generation;
                pending->valid = true;
            } else {
                jt808_session_reject_or_timeout(session, TICK_MS());
                dbg_printf("[808] ch%u register rejected result=%u\r\n",
                           channel, result);
            }
        }
        break;

    case MSG_SET_TERMINAL_PARAM:    /* 0x8103 set parameters */
        s_response_channel = channel;
        jt808_params_handle_set(body, body_len, serial_no);
        break;

    case MSG_QUERY_TERMINAL_PARAM:  /* 0x8104 query parameters */
    case MSG_QUERY_SPECIFIC_PARAM:  /* 0x8106 query selected parameters */
        s_response_channel = channel;
        if ((msg_id == MSG_QUERY_TERMINAL_PARAM && body_len != 0U) ||
            (msg_id == MSG_QUERY_SPECIFIC_PARAM && body_len == 0U)) {
            jt808_send_general_resp(serial_no, msg_id, 2U);
            break;
        }
        jt808_params_handle_query(body, body_len, serial_no);
        break;

    case MSG_QUERY_TERMINAL_INFO:   /* 0x8107 query terminal attributes */
        s_response_channel = channel;
        jt808_params_handle_info_query(serial_no);
        break;

    case MSG_TEXT_MESSAGE:          /* 0x8300 text delivery */
        jt808_send_general_resp_to(channel, serial_no, msg_id,
                                   handle_text_message(body, body_len) ? 0U : 1U);
        break;

    case MSG_SET_POLYGON_AREA:      /* 0x8604 set polygon geofence */
        geofence_handle_jt808(body, body_len, serial_no);
        break;

    case MSG_LOCATION_QUERY:
        s_response_channel = channel;
        (void)send_location_only(MSG_LOCATION_QUERY_RESP);
        break;

    case MSG_TERMINAL_CTRL:
        /* Vendor 0x64/0x65 extension. Use the SMS executor so cut-off keeps
         * the same GNSS/speed safety policy and restore remains unconditional. */
        if (body_len != 1U) {
            jt808_send_general_resp_to(channel, serial_no, msg_id, 2U);
        } else if (body[0] == 0x64U || body[0] == 0x65U) {
            const uint8_t *command = (const uint8_t *)(body[0] == 0x64U ?
                                                      "RELAY,1" : "RELAY,0");
            bool accepted = at_config_execute_text_command(command, 7U);
            jt808_send_general_resp_to(channel, serial_no, msg_id,
                                       accepted ? 0U : 1U);
        } else {
            jt808_send_general_resp_to(channel, serial_no, msg_id, 3U);
        }
        break;

    default:
        jt808_send_general_resp_to(channel, serial_no, msg_id, 0);
        break;
    }

}

bool jt808_is_online(void)
{
    return jt808_online_mask() != 0U;
}

bool jt808_channel_online(uint8_t channel)
{
    jt808_session_t *session = session_for_channel(channel);
    return session != NULL && session->state == JT808_SESSION_ONLINE &&
           tcp_manager_ch_online(channel) &&
           tcp_manager_session_generation(channel) == session->generation;
}

uint8_t jt808_online_mask(void)
{
    uint8_t mask = 0U;
    if (jt808_channel_online(TCP_CH_MAIN)) mask |= (uint8_t)(1U << TCP_CH_MAIN);
    if (jt808_channel_online(TCP_CH_BACKUP)) mask |= (uint8_t)(1U << TCP_CH_BACKUP);
    return mask;
}

uint8_t jt808_online_channel(void)
{ return jt808_channel_online(TCP_CH_MAIN) ? TCP_CH_MAIN : TCP_CH_BACKUP; }

/* ── Called from EC800M receive callback ─────────────────────────────────── */
void jt808_on_recv(uint8_t ch, const uint8_t *data, uint16_t len)
{
    rx_assembly_t *rx;
    uint32_t generation;
    if (data == NULL || len == 0U) return;
    rx = rx_for_channel(ch);
    if (rx == NULL) return;
    trial_discard_trace("[808-RX] ch=%u bytes=%u\r\n", ch, len);
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
    s_identity_log_ms = 0U;
    s_identity_logged = false;
    s_boot_identity_logged = false;
    s_boot_identity_source = TERMINAL_IDENTITY_INVALID_ARGUMENT;
    s_logical_acc_override_set = false;
    s_last_heartbeat_s = 0U;
    s_logical_acc_on = false;
    s_append_pending = false;
    jt808_session_init(&s_sessions[0], TCP_CH_MAIN);
    jt808_session_init(&s_sessions[1], TCP_CH_BACKUP);
    s_response_channel = TCP_CH_MAIN;
    memset(s_rx, 0, sizeof(s_rx));
    memset(s_pending_auth, 0, sizeof(s_pending_auth));
    memset(s_boot_terminal_info, 0, sizeof(s_boot_terminal_info));
    s_tx_workspace.busy = false;
    blind_zone_replay_reset();
    corner_init_safe(&s_motion_corner);
    s_corner_append_pending = false;
    memset(s_corner_snapshot_ms, 0, sizeof(s_corner_snapshot_ms));
    s_corner_last_heading_ms = 0U;
    /* restore auth code from flash so reconnects skip re-registration */
    if (info->auth_code[0])
        strncpy(s_cfg.auth_code, info->auth_code, sizeof(s_cfg.auth_code) - 1);
    {
        device_config_t *config = cfg_get();
        if (config != NULL) {
            if (config->auth_code[0] != '\0')
                strncpy(s_cfg.auth_code, config->auth_code,
                        sizeof(s_cfg.auth_code) - 1U);
            strncpy(s_cfg.backup_auth_code, config->backup_auth_code,
                    sizeof(s_cfg.backup_auth_code) - 1U);
        }
    }
    ec800m_register_recv(jt808_on_recv);
}

void jt808_process(void)
{
    uint32_t now = TICK_MS();
    uint32_t now_s = jt808_monotonic_s();
    static const uint8_t channels[2] = { TCP_CH_MAIN, TCP_CH_BACKUP };
    uint8_t index;
    if (!ec800m_is_ready()) return;

    process_boot_terminal_info(now);
    process_location_timer(now);

    for (index = 0U; index < 2U; ++index) {
        uint8_t channel = channels[index];
        jt808_session_t *session = &s_sessions[index];
        const char *auth = auth_for_channel(channel);
        jt808_session_action_t action;
        pending_auth_t *pending = &s_pending_auth[index];

        jt808_session_sync_link(session, tcp_manager_ch_online(channel),
                                tcp_manager_session_generation(channel));
        if (pending->valid) {
            if (!session->link_open || pending->generation != session->generation) {
                pending->valid = false;
            } else {
                pending->valid = false;
                if (!cfg_set_auth_code(channel, pending->code)) {
                    (void)jt808_session_reject_or_timeout(session, now);
                    continue;
                }
                if (channel == TCP_CH_MAIN)
                    memcpy(s_cfg.auth_code, pending->code, sizeof(pending->code));
                else
                    memcpy(s_cfg.backup_auth_code, pending->code, sizeof(pending->code));
                (void)jt808_send_auth_to(channel, pending->code);
                continue;
            }
        }
        action = jt808_session_next_action(session, auth[0] != '\0', now);
        if (action == JT808_ACTION_NONE) {
            if (session->pending_valid && session->attempts >= 3U &&
                (int32_t)(now - (session->sent_ms + 5000U)) >= 0) {
                /* A missing response is a transport timeout, not proof that
                 * the stored credential is invalid.  Preserve auth so a
                 * reconnect/STOP1 service window never falls back to 0x0100. */
                (void)jt808_session_reject_or_timeout(session, now);
            }
            continue;
        }
        if (!refresh_terminal_identity()) {
            log_identity_invalid(now, terminal_identity_last_result());
            continue;
        }
        log_boot_identity();
        identity_valid();
        if (action == JT808_ACTION_REGISTER) {
            (void)send_register_current_identity(channel);
        } else {
            (void)jt808_send_auth_to(channel, auth);
        }
    }

    /* Heartbeat */
    if (jt808_is_online() &&
        (uint32_t)(now_s - s_last_heartbeat_s) >=
            (uint32_t)s_cfg.heartbeat_s) {
        if (jt808_send_heartbeat() == 0)
            s_last_heartbeat_s = now_s;
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
