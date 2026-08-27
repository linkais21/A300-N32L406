#include "agnss_vendor.h"
#include "debug_uart.h"
#include "ec800m.h"
#include "fota.h"
#include <string.h>
#include <math.h>

#define HUADA_STREAM_MAX 4096U
static uint8_t s_stream[HUADA_STREAM_MAX];
static uint32_t s_stream_len;
static bool s_stream_started;
static bool agnss_ota_active(void){fota_state_t s=fota_get_state();return s==FOTA_STATE_CONNECTING||s==FOTA_STATE_DOWNLOADING||s==FOTA_STATE_VERIFYING;}
static void huada_reset_stream(void){s_stream_len=0;s_stream_started=false;}

static int send_frame(const uint8_t *frame, uint32_t len)
{
    if (!frame || len < 8 || len > 65543UL || frame[0] != 0xF1 || frame[1] != 0xD9) return -1;
    uint16_t plen = (uint16_t)frame[4] | ((uint16_t)frame[5] << 8);
    if ((uint32_t)plen + 8U != len) return -1;
    uint8_t c1 = 0, c2 = 0;
    for (uint32_t i = 2; i < 6U + plen; ++i) { c1 = (uint8_t)(c1 + frame[i]); c2 = (uint8_t)(c2 + c1); }
    if (frame[6U + plen] != c1 || frame[7U + plen] != c2) return -1;
    return gps_send_raw(frame, len);
}

static uint32_t pack(uint8_t *out, const uint8_t *cmd, uint16_t cmd_len)
{
    if (!out || !cmd || cmd_len > 1024U) return 0;
    out[0]=0xF1; out[1]=0xD9; out[2]=cmd[2]; out[3]=cmd[3];
    out[4]=(uint8_t)cmd_len; out[5]=(uint8_t)(cmd_len>>8);
    memcpy(out+6, cmd+4, cmd_len);
    uint8_t c1=0,c2=0; for (uint32_t i=2;i<6U+cmd_len;i++){c1=(uint8_t)(c1+out[i]);c2=(uint8_t)(c2+c1);} out[6+cmd_len]=c1; out[7+cmd_len]=c2;
    return 8U+cmd_len;
}

static int inject_time(const gps_context_t *g)
{
    if (!g || !g->year) return 0;
    uint8_t c[24]={0}, f[32]; c[2]=0x0B;c[3]=0x11;c[4]=0;c[6]=0x12;
    c[7]=(uint8_t)g->year;c[8]=(uint8_t)(g->year>>8);c[9]=g->month;c[10]=g->day;c[11]=g->hour;c[12]=g->minute;c[13]=g->second;
    uint32_t n=pack(f,c,20); return send_frame(f,n);
}

static int inject_location(const gps_context_t *g)
{
    if (!g || !g->valid) return 0;
    uint8_t c[21]={0}, f[32]; int32_t lat=(int32_t)llround(g->lat*1e7), lon=(int32_t)llround(g->lon*1e7); uint32_t alt=(uint32_t)(g->altitude_m*100.0f), acc=0;
    c[2]=0x0B;c[3]=0x10;c[4]=1; for(int i=0;i<4;i++){c[5+i]=(uint8_t)(lat>>(8*i));c[9+i]=(uint8_t)(lon>>(8*i));c[13+i]=(uint8_t)(alt>>(8*i));c[17+i]=(uint8_t)(acc>>(8*i));}
    uint32_t n=pack(f,c,17); return send_frame(f,n);
}

int agnss_huada_inject(const agnss_source_t *src, const gps_context_t *ctx)
{
    if (!s_stream_started) { if (inject_time(ctx)<0 || inject_location(ctx)<0) { huada_reset_stream(); return -1; } s_stream_started=true; s_stream_len=0; }
    if (!src || !src->data || src->len == 0) { int ok = (s_stream_len==0); huada_reset_stream(); return ok ? 0 : -1; }
    if (src->len > HUADA_STREAM_MAX - s_stream_len) { huada_reset_stream(); return -1; }
    memcpy(s_stream+s_stream_len, src->data, src->len); s_stream_len += src->len;
    uint32_t i=0;
    while (s_stream_len - i >= 8U) {
        if (s_stream[i] != 0xF1 || s_stream[i+1] != 0xD9) { ++i; continue; }
        uint16_t n=(uint16_t)s_stream[i+4] | ((uint16_t)s_stream[i+5]<<8); uint32_t total=(uint32_t)n+8U;
        if (total > HUADA_STREAM_MAX || total < 8U) { huada_reset_stream(); return -1; }
        if (s_stream_len - i < total) break;
        if (send_frame(s_stream+i,total)<0) { huada_reset_stream(); return -1; } i += total;
    }
    if (i) { memmove(s_stream,s_stream+i,s_stream_len-i); s_stream_len -= i; }
    return 0;
}

static gnss_type_t s_type = GNSS_TYPE_UNKNOWN;
void gnss_vendor_set_type(gnss_type_t type) { s_type = type; }
bool gnss_vendor_network_rx(uint8_t ch, const uint8_t *data, uint16_t len)
{
    if (ch != EC800M_CH_AGPS || !data || !len || agnss_ota_active()) return false;
    agnss_source_t src={data,len};
    if (s_type == GNSS_TYPE_TAU804M) return agnss_huada_inject(&src,gps_get_data()) == 0;
    if (s_type == GNSS_TYPE_ATGM332D_F7N) return agnss_zhongkewei_request(&src,gps_get_data()) == 0;
    return false;
}

bool gnss_vendor_inject(gnss_type_t type, const uint8_t *data, uint16_t len)
{
    agnss_source_t src = { data, len };
    const gps_context_t *ctx = gps_get_data();
    if (type == GNSS_TYPE_TAU804M) return agnss_huada_inject(&src, ctx) == 0;
    if (type == GNSS_TYPE_ATGM332D_F7N) return agnss_zhongkewei_request(&src, ctx) == 0;
    return 0;
}
