#include "agnss_vendor.h"
#include "flash_config.h"
#include "ec800m.h"
#include "gps.h"
#include <stdio.h>
#include <string.h>

#define ZK_STREAM_MAX 4096U
#define CSIP_HEADER_SIZE 6U
#define CSIP_TRAILER_SIZE 4U
#define CSIP_MIN_SIZE (CSIP_HEADER_SIZE + CSIP_TRAILER_SIZE)
static uint8_t s_rx[ZK_STREAM_MAX]; static uint32_t s_rx_len;

int zhongkewei_build_request(char *out, uint32_t cap, const char *user, const char *pwd, const gps_context_t *ctx)
{
    if (!out || cap == 0 || !user || !pwd || !*user || !*pwd || !ctx) return -1;
    int n=snprintf(out, cap, "user=%s;pwd=%s;cmd=full;lat=%.7f;lon=%.7f;alt=%.2f;", user,pwd,ctx->lat,ctx->lon,(double)ctx->altitude_m);
    return (n < 0 || (uint32_t)n >= cap) ? -1 : n;
}

static uint32_t le32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

static bool csip_msg_allowed(uint8_t id, uint16_t n)
{
    switch (id) {
    case 0x00: return n == 20U;
    case 0x01: return n == 16U;
    case 0x02: return n == 92U;
    case 0x03: return n == 16U;
    case 0x04: return n == 92U;
    case 0x05: return n == 20U;
    case 0x06: return n == 16U;
    case 0x07: return n == 72U;
    case 0x08: return n == 68U;
    case 0x09: return n == 20U;
    case 0x0b: return n == 76U;
    case 0x0c: return n == 20U;
    case 0x0d: return n == 16U;
    case 0x0e: return n == 72U;
    case 0x11: return n == 88U;
    default: return false;
    }
}

zhongkewei_resp_t zhongkewei_parse_csip_frame(const uint8_t *buf, uint32_t len, const uint8_t **frame, uint16_t *frame_len)
{
    uint16_t n;
    uint32_t total, sum;
    if (!buf || !frame || !frame_len) return ZK_RESP_MALFORMED;
    if (len < 2U) return ZK_RESP_INCOMPLETE;
    if (buf[0] != 0xbaU || buf[1] != 0xceU) return ZK_RESP_MALFORMED;
    if (len < 4U) return ZK_RESP_INCOMPLETE;
    n = (uint16_t)buf[2] | ((uint16_t)buf[3] << 8);
    if (n >= 2048U || (n & 3U) != 0U) return ZK_RESP_MALFORMED;
    total = (uint32_t)n + CSIP_MIN_SIZE;
    if (len < total) return ZK_RESP_INCOMPLETE;
    if (buf[4] != 0x08U || !csip_msg_allowed(buf[5], n)) return ZK_RESP_MALFORMED;
    sum = ((uint32_t)buf[5] << 24) + ((uint32_t)buf[4] << 16) + n;
    for (uint16_t i = 0; i < n; i += 4U) sum += le32(buf + CSIP_HEADER_SIZE + i);
    if (le32(buf + CSIP_HEADER_SIZE + n) != sum) return ZK_RESP_MALFORMED;
    *frame = buf;
    *frame_len = (uint16_t)total;
    return ZK_RESP_OK;
}

static void stream_drop(uint32_t n)
{
    if (n >= s_rx_len) { s_rx_len = 0; return; }
    memmove(s_rx, s_rx + n, s_rx_len - n);
    s_rx_len -= n;
}

static int csip_feed(const uint8_t *data, uint32_t len)
{
    uint32_t i;
    if (!data || !len || len > ZK_STREAM_MAX - s_rx_len) { s_rx_len = 0; return -1; }
    memcpy(s_rx + s_rx_len, data, len);
    s_rx_len += len;
    while (s_rx_len) {
        const uint8_t *frame;
        uint16_t frame_len;
        zhongkewei_resp_t st;
        for (i = 0; i + 1U < s_rx_len; ++i) if (s_rx[i] == 0xbaU && s_rx[i + 1U] == 0xceU) break;
        if (i + 1U >= s_rx_len) {
            if (s_rx[s_rx_len - 1U] == 0xbaU) { s_rx[0] = 0xbaU; s_rx_len = 1U; }
            else s_rx_len = 0;
            return 0;
        }
        if (i) stream_drop(i);
        st = zhongkewei_parse_csip_frame(s_rx, s_rx_len, &frame, &frame_len);
        if (st == ZK_RESP_INCOMPLETE) return 0;
        if (st == ZK_RESP_MALFORMED) { s_rx_len = 0; return -1; }
        if (gps_send_raw(frame, frame_len) < 0) { s_rx_len = 0; return -1; }
        stream_drop(frame_len);
    }
    return 0;
}

int agnss_zhongkewei_request(const agnss_source_t *src, const gps_context_t *ctx)
{
    device_config_t *cfg=cfg_get(); char req[256];
    if (src && src->data && src->len) {
        /* Offline CSIP injection is receiver data and needs no server credential. */
        return csip_feed(src->data, src->len);
    }
    /* The receiver specification defines CSIP only. This server request is
     * retained for transport compatibility but remains protocol-unverified. */
    if (!cfg || zhongkewei_build_request(req,sizeof req,cfg->agnss_user,cfg->agnss_pwd,ctx)<0) return -1;
    if (!ec800m_is_ready() || ec800m_tcp_state(EC800M_CH_AGPS) != TCP_STATE_OPEN) return -1;
    return ec800m_tcp_send(EC800M_CH_AGPS, (const uint8_t *)req, (uint16_t)strlen(req));
}
