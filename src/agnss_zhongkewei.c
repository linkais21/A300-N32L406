#include "agnss_vendor.h"
#include "flash_config.h"
#include "ec800m.h"
#include "gps.h"
#include <stdio.h>
#include <string.h>

#define ZK_STREAM_MAX 4096U
static uint8_t s_rx[ZK_STREAM_MAX]; static uint32_t s_rx_len;

int zhongkewei_build_request(char *out, uint32_t cap, const char *user, const char *pwd, const gps_context_t *ctx)
{
    if (!out || cap == 0 || !user || !pwd || !*user || !*pwd || !ctx) return -1;
    int n=snprintf(out, cap, "user=%s;pwd=%s;cmd=full;lat=%.7f;lon=%.7f;alt=%.2f;", user,pwd,ctx->lat,ctx->lon,(double)ctx->altitude_m);
    return (n < 0 || (uint32_t)n >= cap) ? -1 : n;
}

zhongkewei_resp_t zhongkewei_parse_response(const uint8_t *buf, uint32_t len, const uint8_t **payload, uint16_t *payload_len)
{
    if (!buf || !payload || !payload_len) return ZK_RESP_MALFORMED;
    if (len < 2U) return ZK_RESP_INCOMPLETE;
    /* Response is a length-prefixed binary envelope: 'A''G' + uint16 LE length + status + payload + checksum16. */
    if (buf[0] != 'A' || buf[1] != 'G') return ZK_RESP_MALFORMED;
    if (len < 5U) return ZK_RESP_INCOMPLETE;
    uint16_t n=(uint16_t)buf[2] | ((uint16_t)buf[3]<<8); if (n < 3U || n > ZK_STREAM_MAX-8U) return ZK_RESP_MALFORMED;
    uint32_t total=(uint32_t)n+8U; if (len < total) return ZK_RESP_INCOMPLETE; if (len != total) return ZK_RESP_MALFORMED;
    if (buf[4] != 0) return ZK_RESP_MALFORMED;
    uint8_t c1=0,c2=0; for(uint32_t i=2;i<5U+n;i++){c1=(uint8_t)(c1+buf[i]);c2=(uint8_t)(c2+c1);} if(buf[5U+n]!=c1||buf[6U+n]!=c2)return ZK_RESP_MALFORMED;
    *payload=buf+5; *payload_len=(uint16_t)(n-3U); return ZK_RESP_OK;
}

int agnss_zhongkewei_request(const agnss_source_t *src, const gps_context_t *ctx)
{
    device_config_t *cfg=cfg_get(); char req[256];
    if (!cfg || zhongkewei_build_request(req,sizeof req,cfg->agnss_user,cfg->agnss_pwd,ctx)<0) return -1;
    if (src && src->data && src->len) {
        if (src->len > ZK_STREAM_MAX-s_rx_len) { s_rx_len=0; return -1; }
        memcpy(s_rx+s_rx_len,src->data,src->len); s_rx_len += src->len;
        const uint8_t *p; uint16_t n;
        zhongkewei_resp_t st=zhongkewei_parse_response(s_rx,s_rx_len,&p,&n);
        if (st == ZK_RESP_INCOMPLETE) return 0;
        if (st == ZK_RESP_MALFORMED) { s_rx_len=0; return -1; }
        while (n) { uint16_t k = n > 256U ? 256U : n; if (gps_send_raw(p,k)<0) return -1; p += k; n = (uint16_t)(n-k); }
        s_rx_len=0;
        return 0;
    }
    if (!ec800m_is_ready() || ec800m_tcp_state(EC800M_CH_AGPS) != TCP_STATE_OPEN) return -1;
    return ec800m_tcp_send(EC800M_CH_AGPS, (const uint8_t *)req, (uint16_t)strlen(req));
}
