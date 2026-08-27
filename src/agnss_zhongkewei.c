#include "agnss_vendor.h"
#include "flash_config.h"
#include "ec800m.h"
#include "gps.h"
#include <stdio.h>
#include <string.h>

int zhongkewei_build_request(char *out, uint32_t cap, const char *user, const char *pwd, const gps_context_t *ctx)
{
    if (!out || cap == 0 || !user || !pwd || !*user || !*pwd || !ctx) return -1;
    int n=snprintf(out, cap, "user=%s;pwd=%s;cmd=full;lat=%.7f;lon=%.7f;alt=%.2f;", user,pwd,ctx->lat,ctx->lon,(double)ctx->altitude_m);
    return (n < 0 || (uint32_t)n >= cap) ? -1 : n;
}

int zhongkewei_parse_response(const uint8_t *buf, uint32_t len, const uint8_t **payload, uint16_t *payload_len)
{
    if (!buf || !payload || !payload_len || len < 8U) return -1;
    /* Response is a length-prefixed binary envelope: 'A''G' + uint16 LE length + status + payload + checksum16. */
    if (buf[0] != 'A' || buf[1] != 'G') return -1;
    uint16_t n=(uint16_t)buf[2] | ((uint16_t)buf[3]<<8); if (n == 0 || (uint32_t)n + 8U != len || buf[4] != 0) return -1;
    uint8_t c1=0,c2=0; for(uint32_t i=2;i<5U+n;i++){c1=(uint8_t)(c1+buf[i]);c2=(uint8_t)(c2+c1);} if(buf[5U+n]!=c1||buf[6U+n]!=c2)return -1;
    *payload=buf+5; *payload_len=(uint16_t)(n-3U); return 0;
}

int agnss_zhongkewei_request(const agnss_source_t *src, const gps_context_t *ctx)
{
    device_config_t *cfg=cfg_get(); char req[256];
    if (!cfg || zhongkewei_build_request(req,sizeof req,cfg->agnss_user,cfg->agnss_pwd,ctx)<0) return -1;
    if (src && src->data && src->len) {
        const uint8_t *p; uint16_t n;
        if (zhongkewei_parse_response(src->data,src->len,&p,&n)<0) return -1;
        while (n) { uint16_t k = n > 256U ? 256U : n; if (gps_send_raw(p,k)<0) return -1; p += k; n = (uint16_t)(n-k); }
        return 0;
    }
    if (!ec800m_is_ready() || ec800m_tcp_state(EC800M_CH_AGPS) != TCP_STATE_OPEN) return -1;
    return ec800m_tcp_send(EC800M_CH_AGPS, (const uint8_t *)req, (uint16_t)strlen(req));
}
