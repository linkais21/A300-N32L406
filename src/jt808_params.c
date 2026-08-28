#include "jt808_params.h"
#include "jt808.h"
#include "flash_config.h"
#include "ec800m.h"
#include "debug_uart.h"
#include "config.h"
#include "terminal_identity.h"
#include <string.h>
#include <stdlib.h>
#include <stdio.h>

/* ── Read helpers ─────────────────────────────────────────────────────────── */
static uint32_t read_u32(const uint8_t *p)
{
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
           ((uint32_t)p[2] << 8)  |  (uint32_t)p[3];
}

static void write_u32(uint8_t *p, uint32_t v)
{
    p[0]=(v>>24)&0xFF; p[1]=(v>>16)&0xFF;
    p[2]=(v>>8)&0xFF;  p[3]=v&0xFF;
}

/* ── Parse "ip,port" or "ip:port" string ─────────────────────────────────── */
static void parse_server_str(const char *s, char *ip, uint16_t *port)
{
    strncpy(ip, s, CFG_IP_LEN - 1);
    char *sep = strchr(ip, ',');
    if (!sep) sep = strchr(ip, ':');
    if (sep) {
        *port = (uint16_t)atoi(sep + 1);
        *sep  = '\0';
    }
}

/* ── Apply one parameter to live config ──────────────────────────────────── */
static void apply_param(uint32_t id, uint8_t type, const uint8_t *val, uint8_t vlen)
{
    device_config_t *c = cfg_get();
    char str[CFG_IP_LEN]; memset(str, 0, sizeof(str));
    uint32_t u32 = 0;

    if (type == 0x00 && vlen == 4) u32 = read_u32(val);
    if (type == 0x02 || type == 0x03) {
        uint8_t copy = vlen < (uint8_t)(CFG_IP_LEN - 1) ? vlen : CFG_IP_LEN - 1;
        memcpy(str, val, copy); str[copy] = '\0';
    }

    switch (id) {
    case PARAM_HEARTBEAT_INTERVAL:
        c->heartbeat_s = (uint16_t)(u32 < 3600 ? u32 : 3600);
        jt808_set_heartbeat_s(c->heartbeat_s);
        break;
    case PARAM_REPORT_INTERVAL_DEFAULT:
        c->report_moving_s = (uint16_t)(u32 < 18000 ? u32 : 18000);
        if (c->report_moving_s != 0U &&
            c->report_moving_s < JT808_REPORT_INTERVAL_MIN_S)
            c->report_moving_s = JT808_REPORT_INTERVAL_MIN_S;
        break;
    case PARAM_REPORT_INTERVAL_NOACC:
        c->report_stopped_s = (uint16_t)(u32 < 18000 ? u32 : 18000);
        if (c->report_stopped_s != 0U &&
            c->report_stopped_s < JT808_REPORT_INTERVAL_MIN_S)
            c->report_stopped_s = JT808_REPORT_INTERVAL_MIN_S;
        jt808_set_report_interval(c->report_moving_s, c->report_stopped_s);
        break;
    case PARAM_MAIN_SERVER: {
        char ip[CFG_IP_LEN]; uint16_t port = 8898;
        parse_server_str(str, ip, &port);
        cfg_set_server(ip, port, false);
        break;
    }
    case PARAM_BACKUP_SERVER: {
        char ip[CFG_IP_LEN]; uint16_t port = 8898;
        parse_server_str(str, ip, &port);
        cfg_set_server(ip, port, true);
        break;
    }
    case PARAM_SERVER_APN:
        strncpy(c->apn, str, CFG_APN_LEN - 1); break;
    case PARAM_SERVER_APN_USER:
        strncpy(c->apn_user, str, CFG_USER_LEN - 1); break;
    case PARAM_SERVER_APN_PASS:
        strncpy(c->apn_pass, str, CFG_PASS_LEN - 1); break;
    case PARAM_PLATFORM_PHONE:
        strncpy(c->phone, str, CFG_PHONE_LEN - 1); break;
    default:
        dbg_printf("[808] unknown param 0x%x (type=%u len=%u)\r\n",
                   (unsigned)id, type, vlen);
        break;
    }
}

/* ── 0x8103 SET ───────────────────────────────────────────────────────────── */
void jt808_params_handle_set(const uint8_t *body, uint16_t len, uint16_t sn)
{
    if (len < 1) goto done;
    uint8_t count = body[0];
    uint16_t pos  = 1;

    for (uint8_t i = 0; i < count && pos + 5 < len; i++) {
        uint32_t pid  = read_u32(&body[pos]);  pos += 4;
        uint8_t  plen = body[pos++];
        if (pos + plen > len) break;

        /* Determine type from length: 1=byte 2=word 4=dword else=string */
        uint8_t ptype = (plen == 4) ? 0x00 : 0x02;
        apply_param(pid, ptype, &body[pos], plen);
        pos += plen;
    }
    cfg_save();
done:
    jt808_send_general_resp(sn, MSG_SET_TERMINAL_PARAM, 0);
    dbg_printf("[808] 0x8103 param set (%u params)\r\n", body[0]);
}

/* ── Build parameter response body ──────────────────────────────────────── */
static uint16_t build_param_item(uint8_t *buf, uint32_t id,
                                 const void *val, uint8_t vlen)
{
    write_u32(buf, id);
    buf[4] = vlen;
    memcpy(buf + 5, val, vlen);
    return 5 + vlen;
}

/* ── 0x8104 QUERY specific params / 0x8106 full dump ─────────────────────── */
void jt808_params_handle_query(const uint8_t *body, uint16_t len, uint16_t sn)
{
    device_config_t *c = cfg_get();
    uint8_t resp_body[512];
    uint16_t pos = 0;
    uint32_t u32;

    /* Number of params placeholder at pos=0 */
    resp_body[pos++] = 0x00;   /* filled in later */
    uint8_t count = 0;

    /* If body is empty → respond with all supported params */
    bool query_all = (len == 0);
    uint8_t req_count = (len >= 1) ? body[0] : 0;

    #define ADD_U32(ID, VAL) \
        u32 = (VAL); \
        pos += build_param_item(resp_body + pos, (ID), &u32, 4); count++

    #define ADD_STR(ID, STR) \
        pos += build_param_item(resp_body + pos, (ID), (STR), \
               (uint8_t)strlen(STR)); count++

    if (query_all || req_count == 0) {
        /* Respond with all known params */
        ADD_U32(PARAM_HEARTBEAT_INTERVAL,    (uint32_t)c->heartbeat_s);
        ADD_U32(PARAM_REPORT_INTERVAL_DEFAULT,(uint32_t)c->report_moving_s);
        ADD_U32(PARAM_REPORT_INTERVAL_NOACC, (uint32_t)c->report_stopped_s);
        ADD_STR(PARAM_SERVER_APN,            c->apn);
        ADD_STR(PARAM_SERVER_APN_USER,       c->apn_user);

        char srv[CFG_IP_LEN + 8];
        snprintf(srv, sizeof(srv), "%s,%u", c->server_ip, c->server_port);
        ADD_STR(PARAM_MAIN_SERVER, srv);
        snprintf(srv, sizeof(srv), "%s,%u", c->backup_ip, c->backup_port);
        ADD_STR(PARAM_BACKUP_SERVER, srv);
    } else {
        for (uint8_t i = 0; i < req_count && pos + 4 <= len; i++) {
            uint32_t pid = read_u32(&body[1 + i * 4]);
            switch (pid) {
            case PARAM_HEARTBEAT_INTERVAL:
                ADD_U32(pid, (uint32_t)c->heartbeat_s); break;
            case PARAM_REPORT_INTERVAL_DEFAULT:
                ADD_U32(pid, (uint32_t)c->report_moving_s); break;
            case PARAM_REPORT_INTERVAL_NOACC:
                ADD_U32(pid, (uint32_t)c->report_stopped_s); break;
            case PARAM_MAIN_SERVER: {
                char srv[CFG_IP_LEN+8];
                snprintf(srv, sizeof(srv), "%s,%u",
                         c->server_ip, c->server_port);
                ADD_STR(pid, srv); break; }
            case PARAM_BACKUP_SERVER: {
                char srv[CFG_IP_LEN+8];
                snprintf(srv, sizeof(srv), "%s,%u",
                         c->backup_ip, c->backup_port);
                ADD_STR(pid, srv); break; }
            default: break;
            }
        }
    }

    resp_body[0] = count;

    /* Send as 0x0104 response (terminal parameter query response) */
    extern int jt808_send_raw(uint16_t msg_id, uint16_t resp_sn,
                              const uint8_t *body, uint16_t blen);
    jt808_send_raw(0x0104, sn, resp_body, pos);
    dbg_printf("[808] 0x8104 query response (%u params)\r\n", count);

    #undef ADD_U32
    #undef ADD_STR
}

/* ── 0x8107 Terminal info query ───────────────────────────────────────────── */
void jt808_params_handle_info_query(uint16_t sn)
{
    uint8_t body[96];
    uint16_t pos = 0;
    char tid[8];

    if (!terminal_identity_load(tid)) {
        jt808_send_general_resp(sn, MSG_QUERY_TERMINAL_INFO, 1U);
        dbg_printf("[808] 0x8107 identity invalid\r\n");
        return;
    }

    /* Terminal type flags */
    body[pos++] = 0x00; body[pos++] = 0x07;  /* passenger + dangerous goods + bus */
    /* Manufacturer ID (5 bytes) */
    const char *mfr = "CYHLL";
    memcpy(body + pos, mfr, 5); pos += 5;
    /* Terminal model (20 bytes) */
    char model[20]; memset(model, 0, 20);
    strncpy(model, FW_MODEL_STR, 19);
    memcpy(body + pos, model, 20); pos += 20;
    /* Terminal ID (7 bytes) */
    memcpy(body + pos, tid, 7); pos += 7;
    /* ICCID (10 bytes BCD) */
    memset(body + pos, 0, 10); pos += 10;
    /* HW version length + bytes (no separate hardware version configured). */
    body[pos++] = 0U;
    /* FW version length + complete release version. */
    size_t fwv_len = strlen(FW_VERSION_STR);
    if (fwv_len > 255U || pos + 1U + fwv_len + 2U > sizeof(body)) {
        jt808_send_general_resp(sn, MSG_QUERY_TERMINAL_INFO, 1U);
        return;
    }
    body[pos++] = (uint8_t)fwv_len;
    memcpy(body + pos, FW_VERSION_STR, fwv_len); pos += (uint16_t)fwv_len;
    /* GNSS properties: BDS+GPS+GLONASS */
    body[pos++] = 0x07;
    /* Communication properties: LTE */
    body[pos++] = 0x04;

    extern int jt808_send_raw(uint16_t msg_id, uint16_t resp_sn,
                              const uint8_t *body, uint16_t blen);
    jt808_send_raw(0x0107, sn, body, pos);
}
