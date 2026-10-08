#include "agnss_vendor.h"
#include "debug_uart.h"
#include "ec800m.h"
#include "fota.h"
#include "agnss_stream_workspace.h"
#include "huada_ack.h"
#include "config.h"
#include <string.h>
#include <math.h>

#ifdef A300_HARDWARE_BRINGUP
int agnss_huada_inject(const agnss_source_t *src, const gps_context_t *ctx)
{ (void)src; (void)ctx; return -1; }
void gnss_vendor_set_type(gnss_type_t type) { (void)type; }
bool gnss_vendor_network_rx(uint8_t ch, const uint8_t *data, uint16_t len)
{ (void)ch; (void)data; (void)len; return false; }
bool gnss_vendor_inject(gnss_type_t type, const uint8_t *data, uint16_t len)
{ (void)type; (void)data; (void)len; return false; }
bool gnss_vendor_inject_pending(void) { return false; }
#else
#define HUADA_STREAM_MAX 4096U
#define HUADA_COLD_SETTLE_MS 1000U
enum { HUADA_STAGE_TIME, HUADA_STAGE_POS, HUADA_STAGE_DATA, HUADA_STAGE_COLD_SETTLE };
static uint32_t s_stream_len;
static uint32_t s_cold_done_ms;
static bool s_stream_started;
static bool s_chunk_active;
static bool s_frame_active;
static uint16_t s_frame_len;
static uint8_t s_stage;
static bool s_ack_waiting;
static bool s_failed;
static uint32_t s_ack_sequence;
static huada_ack_t s_ack;
static uint8_t *huada_stream(void)
{
    return agnss_stream_workspace_buffer(AGNSS_STREAM_OWNER_HUADA, NULL);
}
static void huada_reset_stream(void)
{
    huada_ack_cancel(&s_ack);
    s_stream_len=0;s_stream_started=false;s_chunk_active=false;
    s_frame_active=false;s_frame_len=0;s_stage=HUADA_STAGE_TIME;
    s_ack_waiting=false;s_failed=false;s_ack_sequence=0;s_cold_done_ms=0;
    agnss_stream_workspace_release(AGNSS_STREAM_OWNER_HUADA);
}

static int send_ack_frame(const uint8_t *frame, uint16_t len)
{
    return gps_send_raw(frame,len);
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

static uint16_t build_location(const gps_context_t *g, uint8_t f[32])
{
    if (!g || !g->valid || !(g->lat>=-90.0 && g->lat<=90.0 &&
        g->lon>=-180.0 && g->lon<=180.0 && g->altitude_m>=-21474834.0f &&
        g->altitude_m<=21474834.0f)) return 0;
    uint8_t c[21]={0};
    double y=g->lat*1e7,x=g->lon*1e7;
    int32_t lat=(int32_t)(y+(y<0?-0.5:0.5));
    int32_t lon=(int32_t)(x+(x<0?-0.5:0.5));
    uint32_t alt=(uint32_t)(int32_t)(g->altitude_m*100.0f);
    c[2]=0x0B;c[3]=0x10;c[4]=1;
    for(int i=0;i<4;i++){c[5+i]=(uint8_t)(lat>>(8*i));c[9+i]=(uint8_t)(lon>>(8*i));c[13+i]=(uint8_t)(alt>>(8*i));}
    return (uint16_t)pack(f,c,17);
}

static int start_ack(const uint8_t *frame, uint16_t len)
{
    s_ack_sequence=gps_agnss_ack_sequence();
    if (!huada_ack_start(&s_ack,frame,len,TICK_MS(),1000U,send_ack_frame)) {
        s_failed=true;
        return -1;
    }
    s_ack_waiting=true;
    return 1;
}

static int poll_ack(void)
{
    uint8_t frame[10];
    if (!s_ack_waiting) return 0;
    if (gps_agnss_take_ack(&s_ack_sequence,frame))
        huada_ack_receive(&s_ack,frame,sizeof frame,TICK_MS());
    huada_ack_poll(&s_ack,TICK_MS());
    if (s_ack.state == HUADA_ACK_WAIT) return 1;
    if (s_ack.state != HUADA_ACK_OK) {
        huada_reset_stream();
        return -1;
    }
    s_ack_waiting=false;
    if (s_frame_active) {
        memmove(huada_stream(),huada_stream()+s_frame_len,s_stream_len-s_frame_len);
        s_stream_len-=s_frame_len;
        s_frame_active=false;
        s_frame_len=0;
    }
    return 0;
}

static int start_metadata(const gps_context_t *ctx)
{
    gps_context_t utc;
    uint8_t f[32];
    uint32_t n;
    if (s_stage == HUADA_STAGE_TIME) {
        /* NTP/retained UTC is the only time source accepted for AID-TIME. */
        gps_get_unfixed_report(&utc);
        s_stage=HUADA_STAGE_POS;
        if (utc.year) {
            uint8_t c[24]={0};
            c[2]=0x0B;c[3]=0x11;c[4]=0;c[6]=1;
            c[7]=(uint8_t)utc.year;c[8]=(uint8_t)(utc.year>>8);
            c[9]=utc.month;c[10]=utc.day;c[11]=utc.hour;
            c[12]=utc.minute;c[13]=utc.second;
            n=pack(f,c,20);
            return start_ack(f,(uint16_t)n);
        }
    }
    if (s_stage == HUADA_STAGE_POS) {
        s_stage=HUADA_STAGE_DATA;
        n=build_location(ctx,f);
        if (n) return start_ack(f,(uint16_t)n);
    }
    return 0;
}

int agnss_huada_inject(const agnss_source_t *src, const gps_context_t *ctx)
{
    uint8_t *s_stream;
    if (!s_stream_started) {
        if (!agnss_stream_workspace_try_acquire(AGNSS_STREAM_OWNER_HUADA))
            return -1;
        static const uint8_t cold_start[] = {0xF1,0xD9,0x06,0x40,0x01,0x00,0x01,0x48,0x22};
        if (gps_send_raw(cold_start,sizeof cold_start) != 0) { huada_reset_stream(); return -1; }
        s_stream_started=true; s_stream_len=0;
        /* Start the settle window after the last cold-start byte is sent. */
        s_cold_done_ms=TICK_MS();s_stage=HUADA_STAGE_COLD_SETTLE;
    }
    if (s_failed) { huada_reset_stream(); return -1; }
    if (s_stage == HUADA_STAGE_COLD_SETTLE) {
        if ((uint32_t)(TICK_MS()-s_cold_done_ms) < HUADA_COLD_SETTLE_MS) return 1;
        s_stage=HUADA_STAGE_TIME;
    }
    if (s_ack_waiting) {
        int p=poll_ack();
        if (p) return p;
    }
    if (s_chunk_active) {
        /* The manager retries the same storage offset until this chunk's
         * complete set of frames has received ACKs. */
    } else if (src && src->data && src->len) {
        if (src->len > HUADA_STREAM_MAX - s_stream_len) { huada_reset_stream(); return -1; }
        s_stream=huada_stream();
        if (!s_stream) { huada_reset_stream(); return -1; }
        memcpy(s_stream+s_stream_len,src->data,src->len); s_stream_len+=src->len;
        s_chunk_active=true;
    }
    if (s_stage != HUADA_STAGE_DATA) {
        int p=start_metadata(ctx);
        if (p) {
            if (p < 0) huada_reset_stream();
            return p;
        }
    }
    s_stream = huada_stream();
    if (s_stream == NULL) { huada_reset_stream(); return -1; }
    uint32_t i=0;
    if (s_frame_active) return 1;
    while (s_stream_len - i >= 8U) {
        if (s_stream[i] != 0xF1 || s_stream[i+1] != 0xD9) { ++i; continue; }
        uint16_t n=(uint16_t)s_stream[i+4] | ((uint16_t)s_stream[i+5]<<8); uint32_t total=(uint32_t)n+8U;
        if (total > HUADA_STREAM_MAX || total < 8U) { huada_reset_stream(); return -1; }
        if (s_stream_len - i < total) break;
        if (!huada_aid_frame_valid(s_stream+i,(uint16_t)total) || s_stream[i+3] != 0x33) { huada_reset_stream(); return -1; }
        if (i) { memmove(s_stream,s_stream+i,s_stream_len-i); s_stream_len-=i; }
        s_frame_active=true;s_frame_len=(uint16_t)total;
        return start_ack(s_stream,s_frame_len);
    }
    if (i) { memmove(s_stream,s_stream+i,s_stream_len-i); s_stream_len -= i; }
    if (s_ack_waiting) return 1;
    if (s_chunk_active) { s_chunk_active=false; return 0; }
    if (!src || !src->data || src->len == 0) {
        int ok = (s_stream_len==0);
        huada_reset_stream();
        return ok ? 0 : -1;
    }
    return 0;
}

static gnss_type_t s_type = GNSS_TYPE_UNKNOWN;
void gnss_vendor_set_type(gnss_type_t type) { s_type = type; }
bool gnss_vendor_network_rx(uint8_t ch, const uint8_t *data, uint16_t len)
{
    if (ch != EC800M_CH_AGPS || !data || !len || fota_is_active()) return false;
    agnss_source_t src={data,len};
    if (s_type == GNSS_TYPE_TAU804M) return agnss_huada_inject(&src,gps_get_data()) == 0;
    return false;
}

bool gnss_vendor_inject(gnss_type_t type, const uint8_t *data, uint16_t len)
{
    agnss_source_t src = { data, len };
    const gps_context_t *ctx = gps_get_data();
    if (type == GNSS_TYPE_TAU804M) return agnss_huada_inject(&src, ctx) == 0;
    return 0;
}

bool gnss_vendor_inject_pending(void)
{
    return (s_stream_started && s_stage == HUADA_STAGE_COLD_SETTLE) ||
           s_ack_waiting || s_frame_active;
}
#endif
