#include "jt808_params.h"
#include "jt808.h"
#include "flash_config.h"
#include "debug_uart.h"
#include "jt808_terminal_info.h"
#include "service_workspace.h"
#include "tcp_manager.h"
#include "config.h"
#include "ec800m.h"
#include "work_mode.h"
#include "work_mode_sleep.h"
#include <stddef.h>
#include <string.h>

/* Wire types belong to IDs, never to the received length. */
typedef struct { uint16_t id, offset; uint8_t size, wire; } param_t;
#define FIELD(id, field, wire) {id, offsetof(device_config_t, field), sizeof(((device_config_t *)0)->field), wire}
static const param_t params[] = {
    FIELD(PARAM_HEARTBEAT_INTERVAL, heartbeat_s, 4),
    FIELD(PARAM_MAIN_SERVER, server_ip, 0),
    FIELD(PARAM_TCP_PORT, server_port, 4),
    /* Fixed supported modes; no new persistent fields or migration. */
    {PARAM_REPORT_STRATEGY, 0, 0, 4},
    {PARAM_REPORT_SCHEME, 0, 0, 4},
    FIELD(PARAM_REPORT_INTERVAL_NOACC, report_stopped_s, 4),
    FIELD(PARAM_REPORT_INTERVAL_DEFAULT, report_moving_s, 4),
    FIELD(PARAM_SPEED_LIMIT, speed_limit_kmh, 4),
    FIELD(PARAM_MILEAGE, mileage_m, 4),
    FIELD(PARAM_PROVINCE, province_be, 2),
    FIELD(PARAM_CITY, city_be, 2),
    FIELD(PARAM_PLATE, plate_no, 0),
    FIELD(PARAM_PLATE_COLOR, plate_color, 1),
    FIELD(PARAM_BACKUP_SERVER, backup_ip, 0),
    FIELD(PARAM_SERVER_APN, apn, 0),
    FIELD(PARAM_SERVER_APN_USER, apn_user, 0),
    FIELD(PARAM_SERVER_APN_PASS, apn_pass, 0),
    FIELD(PARAM_PLATFORM_PHONE, phone, 0),
};
#define PARAM_COUNT (sizeof(params) / sizeof(params[0]))
typedef char candidate_fits_workspace[(sizeof(device_config_t) <= SERVICE_WORKSPACE_CAPACITY) ? 1 : -1];

static uint32_t read_be(const uint8_t *p, uint8_t n)
{
    uint32_t v = 0U;
    while (n-- != 0U) v = (v << 8) | *p++;
    return v;
}
static void write_be(uint8_t *p, uint32_t v, uint8_t n)
{
    while (n != 0U) { p[--n] = (uint8_t)v; v >>= 8; }
}
static unsigned find_param(uint32_t id)
{
    unsigned i;
    for (i = 0U; i < PARAM_COUNT && params[i].id != id; ++i) {}
    return i;
}
static bool apply_param(device_config_t *c, const param_t *p, const uint8_t *v, uint8_t n)
{
    uint8_t *dst = (uint8_t *)c + p->offset;
    uint32_t value;
    if (p->wire == 0U) {
        if (n >= p->size || memchr(v, 0, n) != NULL) return false;
        if ((p->id == PARAM_MAIN_SERVER || p->id == PARAM_PLATE) && n == 0U) return false;
        for (uint8_t i = 0U; i < n; ++i) {
            if (v[i] < 0x20U || v[i] == 0x7fU) return false;
            if ((p->id == PARAM_SERVER_APN || p->id == PARAM_SERVER_APN_USER ||
                 p->id == PARAM_SERVER_APN_PASS) &&
                (v[i] >= 0x7fU || v[i] == '"' || v[i] == '\\')) return false;
            if ((p->id == PARAM_MAIN_SERVER || p->id == PARAM_BACKUP_SERVER) &&
                !((v[i] >= 'a' && v[i] <= 'z') || (v[i] >= 'A' && v[i] <= 'Z') ||
                  (v[i] >= '0' && v[i] <= '9') || v[i] == '.' || v[i] == '-')) return false;
        }
        /* Preserve GBK wire bytes, including the complete final character. */
        if (p->id == PARAM_PLATE) {
            for (uint8_t i = 0U; i < n; ++i) {
                if (v[i] >= 0x80U && (v[i] < 0x81U || v[i] > 0xfeU || ++i >= n ||
                    v[i] < 0x40U || v[i] > 0xfeU || v[i] == 0x7fU)) return false;
            }
        }
        memset(dst, 0, p->size); memcpy(dst, v, n);
        if (p->id == PARAM_SERVER_APN) c->autoapn_en = n == 0U ? 1U : 0U;
        return true;
    }
    if (n != p->wire) return false;
    value = read_be(v, n);
    switch (p->id) {
    case PARAM_REPORT_STRATEGY:
    case PARAM_REPORT_SCHEME: return value == 0U;
    case PARAM_SPEED_LIMIT:
        /* Same supported range as SPEED and overspeed_policy_step(). */
        if (value < 20U || value > 200U) return false;
        c->speed_limit_kmh = (uint16_t)value; break;
    case PARAM_HEARTBEAT_INTERVAL:
        if (value == 0U || value > 3600U) return false;
        c->heartbeat_s = (uint16_t)value; break;
    case PARAM_REPORT_INTERVAL_NOACC:
    case PARAM_REPORT_INTERVAL_DEFAULT: {
        uint16_t seconds;
        if (value < JT808_REPORT_INTERVAL_MIN_S || value > 18000U) return false;
        seconds = (uint16_t)value; memcpy(dst, &seconds, sizeof seconds); break;
    }
    case PARAM_TCP_PORT:
        if (value == 0U || value > 65535U) return false;
        /* FIP is an independent endpoint, configured by the FIP command.
         * A main-platform port update must not overwrite its saved port. */
        c->server_port = (uint16_t)value; break;
    case PARAM_MILEAGE:
        if (value > UINT32_MAX / 100U) return false;
        c->mileage_m = value * 100U; break;
    case PARAM_PROVINCE:
    case PARAM_CITY: memcpy(dst, v, 2U); break;
    case PARAM_PLATE_COLOR:
        /* 0 unlicensed; JT/T415-2006: 1 blue, 2 yellow, 3 black,
         * 4 white, 9 other. */
        if (value > 4U && value != 9U) return false;
        c->plate_color = (uint8_t)value; c->plate_color_valid = 1U; break;
    default: return false;
    }
    return true;
}

void jt808_params_handle_set(const uint8_t *body, uint16_t len, uint16_t sn)
{
    uint8_t result = 2U, reset_mask = 0U, network_mask = 0U;
    bool changed = false, acquired = false, apn_changed = false;
    uint16_t pos = 1U;
    uint32_t seen = 0U;
    device_config_t *c;
    const device_config_t *old = cfg_get();
    if (body == NULL || len < 1U || body[0] == 0U) goto done;
    if (!service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_PARAMS)) { result = 1U; goto done; }
    acquired = true;
    c = (device_config_t *)service_workspace_buffer(NULL);
    *c = *old;
    for (unsigned i = 0U; i < body[0]; ++i) {
        unsigned index;
        uint8_t n;
        if ((uint32_t)pos + 5U > len) goto done;
        index = find_param(read_be(body + pos, 4U)); pos += 4U;
        n = body[pos++];
        if ((uint32_t)pos + n > len) goto done;
        if (index == PARAM_COUNT) { result = 3U; goto done; }
        if ((seen & (1UL << index)) != 0U) goto done;
        seen |= 1UL << index;
        if ((params[index].id == PARAM_REPORT_STRATEGY ||
             params[index].id == PARAM_REPORT_SCHEME) && n == 4U &&
            read_be(body + pos, n) != 0U) { result = 3U; goto done; }
        if (!apply_param(c, &params[index], body + pos, n)) goto done;
        pos += n;
    }
    if (pos != len) goto done;
    apn_changed = c->autoapn_en != old->autoapn_en || strcmp(c->apn, old->apn) != 0 ||
                  strcmp(c->apn_user, old->apn_user) != 0 || strcmp(c->apn_pass, old->apn_pass) != 0;
    if (strcmp(c->server_ip, old->server_ip) != 0 || c->server_port != old->server_port)
        reset_mask |= JT808_ENDPOINT_MAIN_MASK;
    if (strcmp(c->backup_ip, old->backup_ip) != 0 || c->backup_port != old->backup_port)
        reset_mask |= JT808_ENDPOINT_BACKUP_MASK;
    network_mask = reset_mask;
    if (memcmp(c->province_be, old->province_be, 2U) != 0 || memcmp(c->city_be, old->city_be, 2U) != 0 ||
        c->plate_color != old->plate_color || c->plate_color_valid != old->plate_color_valid ||
        strcmp(c->plate_no, old->plate_no) != 0)
        reset_mask |= JT808_ENDPOINT_MAIN_MASK | JT808_ENDPOINT_BACKUP_MASK;
    if (reset_mask & JT808_ENDPOINT_MAIN_MASK) memset(c->auth_code, 0, sizeof c->auth_code);
    if (reset_mask & JT808_ENDPOINT_BACKUP_MASK) memset(c->backup_auth_code, 0, sizeof c->backup_auth_code);
    changed = memcmp(c, old, sizeof *c) != 0;
    if (changed && !cfg_store_candidate(c)) { changed = false; result = 1U; goto done; }
    result = 0U;
done:
    if (acquired) service_workspace_release(SERVICE_WORKSPACE_OWNER_PARAMS);
    /* Reply on the old connection before scheduling endpoint changes. */
    jt808_send_general_resp(sn, MSG_SET_TERMINAL_PARAM, result);
    if (result == 0U && changed) {
        const device_config_t *live = cfg_get();
        jt808_set_heartbeat_s(live->heartbeat_s);
        jt808_set_report_interval(live->report_moving_s, live->report_stopped_s);
        work_mode_config_changed(live, work_mode_sleep_monotonic_s());
        jt808_set_terminal_profile(live->terminal_model, live->plate_no);
        if (reset_mask != 0U) jt808_reset_endpoint_auth(reset_mask);
        if (apn_changed) {
            tcp_manager_request_reconnect();
            ec800m_restart_pdp();
        } else if (network_mask != 0U) {
            /* The committed config is already the connection manager's source.
             * Keep the unaffected endpoint online, including during OTA deferral. */
            uint8_t channels = 0U;
            if (network_mask & JT808_ENDPOINT_MAIN_MASK) channels |= 1U << TCP_CH_MAIN;
            if (network_mask & JT808_ENDPOINT_BACKUP_MASK) channels |= 1U << TCP_CH_BACKUP;
            tcp_manager_reconnect_channels(channels);
        }
    }
    dbg_printf("[808] 0x8103 result=%u\r\n", result);
}

static uint8_t encode_value(const device_config_t *c, const param_t *p, uint8_t *out)
{
    const uint8_t *src = (const uint8_t *)c + p->offset;
    uint32_t value;
    if (p->id == PARAM_PLATE) return jt808_encode_plate_gbk(c->plate_no, out, CFG_PLATE_LEN);
    if (p->wire == 0U) {
        uint8_t n = 0U;
        while (n < p->size && src[n] != 0U) ++n;
        memcpy(out, src, n); return n;
    }
    if (p->id == PARAM_REPORT_STRATEGY || p->id == PARAM_REPORT_SCHEME) value = 0U;
    else if (p->id == PARAM_MILEAGE) value = c->mileage_m / 100U;
    else if (p->id == PARAM_PLATE_COLOR) value = c->plate_color_valid == 1U ? c->plate_color : 1U;
    else if (p->wire == 2U) value = read_be(src, 2U);
    else { uint16_t v; memcpy(&v, src, sizeof v); value = v; }
    write_be(out, value, p->wire); return p->wire;
}

void jt808_params_handle_query(const uint8_t *body, uint16_t len, uint16_t sn)
{
    uint16_t pos = 3U;
    uint8_t count = 0U, *out;
    uint32_t seen = 0U;
    unsigned requests = len == 0U ? PARAM_COUNT : (body != NULL ? body[0] : 0U);
    uint16_t request_id = len == 0U ? MSG_QUERY_TERMINAL_PARAM : MSG_QUERY_SPECIFIC_PARAM;
    if (len != 0U && (body == NULL || requests == 0U || len != 1U + 4U * requests)) {
        jt808_send_general_resp(sn, request_id, 2U); return;
    }
    if (!service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_PARAMS)) {
        jt808_send_general_resp(sn, request_id, 1U); return;
    }
    out = service_workspace_buffer(NULL); write_be(out, sn, 2U);
    for (unsigned i = 0U; i < requests; ++i) {
        unsigned index = len == 0U ? i : find_param(read_be(body + 1U + i * 4U, 4U));
        const param_t *p;
        uint8_t n;
        if (index == PARAM_COUNT || (seen & (1UL << index)) != 0U) continue;
        seen |= 1UL << index; p = &params[index];
        if ((uint32_t)pos + 5U + p->size + p->wire > SERVICE_WORKSPACE_CAPACITY) {
            service_workspace_release(SERVICE_WORKSPACE_OWNER_PARAMS);
            jt808_send_general_resp(sn, request_id, 1U); return;
        }
        write_be(out + pos, p->id, 4U);
        n = encode_value(cfg_get(), p, out + pos + 5U);
        out[pos + 4U] = n; pos += 5U + n; ++count;
    }
    out[2] = count;
    jt808_send_raw(0x0104U, sn, out, pos);
    service_workspace_release(SERVICE_WORKSPACE_OWNER_PARAMS);
}

void jt808_params_handle_info_query(uint16_t sn)
{
    uint8_t body[JT808_TERMINAL_INFO_BODY_LENGTH];
    uint16_t length;
    jt808_terminal_info_result_t result =
        jt808_terminal_info_encode(body, sizeof(body), &length);

    if (result != JT808_TERMINAL_INFO_OK) {
        jt808_send_general_resp(sn, MSG_QUERY_TERMINAL_INFO, 1U);
        dbg_printf("[808] 0x8107 terminal info unavailable reason=%u\r\n",
                   (unsigned)result);
        return;
    }
    jt808_send_raw(0x0107U, sn, body, length);
}
