#include "agnss_online.h"
#include "agnss_stream_workspace.h"
#include "huada_ack.h"
#include "config.h"
#include "flash_config.h"
#include "ec800m.h"
#include "gps.h"
#include "fota.h"
#include "debug_uart.h"
#include <stdio.h>
#include "a300_format.h"
#include <string.h>

enum { IDLE, OPENING, RECEIVING, VALIDATING, COLD_START, SENDING, WAIT_ACK, FAILED, COLD_SETTLE };
#define HUADA_COLD_SETTLE_MS 1000U
enum { LOCAL_TIME, LOCAL_POS, NETWORK_DATA };
static uint8_t s_phase;
static bool s_header, s_done, s_attempted, s_socket;
static uint16_t s_used, s_expected, s_offset;
static uint16_t s_http_status, s_tx_frames, s_ack_frames, s_ack_seen;
static uint8_t s_last_id;
static uint8_t s_local_stage;
static uint16_t s_local_len;
static uint8_t s_local_frame[32];
static const char *s_reason;
static uint8_t s_trace_ack[10];
static uint16_t s_trace_tx_len;
static bool s_trace_ack_seen;
static uint32_t s_trace_cold_ms, s_trace_tx_ms, s_trace_rx_ms;
/* IDLE retry epoch and active transaction epoch have disjoint lifetimes. */
static uint32_t s_epoch, s_ack_sequence;
static huada_ack_t s_ack;

static uint8_t *buffer(void)
{
    return agnss_stream_workspace_buffer(AGNSS_STREAM_OWNER_ONLINE, NULL);
}

static const char *endpoint_host(void)
{
    const device_config_t *c=cfg_get();
    if(!c->agps_ip[0] || !memcmp(c->agps_ip,"0.0.0.0",8))return "39.108.211.33";
    for(unsigned i=0;i<sizeof c->agps_ip;i++) {
        char v=c->agps_ip[i];
        if(!v)return c->agps_ip;
        if(!((v>='a'&&v<='z')||(v>='A'&&v<='Z')||(v>='0'&&v<='9')||v=='.'||v=='-'))return NULL;
    }
    return NULL;
}

static void trace_hex(const char *label, const uint8_t *bytes, uint16_t len)
{
    static const char hex[] = "0123456789abcdef";
    dbg_printf("[AGNSS-%s] n=%u data=", label, (unsigned)len);
    for (uint16_t i=0; i<len; ++i) {
        dbg_putchar(hex[bytes[i] >> 4]);
        dbg_putchar(hex[bytes[i] & 0x0f]);
    }
    dbg_printf("\r\n");
}

static void finish(bool success)
{
    bool close = s_socket;
    uint8_t stage = s_phase;
    const uint8_t *first = NULL;
    uint16_t first_len = 0;
    if (!success && s_ack.state == HUADA_ACK_NAK && s_tx_frames == 1U &&
        s_offset == 0U && s_trace_ack_seen && s_expected >= 8U) {
        if (s_local_stage != NETWORK_DATA) {
            first = s_local_frame;
            first_len = s_local_len;
        } else {
            first = buffer();
            first_len = (uint16_t)((uint16_t)first[4] +
                                   ((uint16_t)first[5] << 8) + 8U);
        }
        if (first_len != s_trace_tx_len) first_len = 0;
    }
    s_socket=false;s_phase=IDLE;s_epoch=TICK_MS();s_attempted=true;
    s_done=success;
    if(close)ec800m_tcp_close(EC800M_CH_AGPS);
    if (first_len) {
        dbg_printf("[AGNSS-RAW] cold_to_tx=%lu tx_to_rx=%lu ms\r\n",
                   (unsigned long)(s_trace_tx_ms-s_trace_cold_ms),
                   (unsigned long)(s_trace_rx_ms-s_trace_tx_ms));
        trace_hex("TX", first, first_len);
        trace_hex("RX", s_trace_ack, sizeof s_trace_ack);
    }
    huada_ack_cancel(&s_ack);
    agnss_stream_workspace_release(AGNSS_STREAM_OWNER_ONLINE);
    dbg_printf("[AGNSS] result=%u stage=%u reason=%s http=%u rx=%u/%u tx=%u ack=%u seen=%u id=%02x\r\n",
               success?1U:0U, (unsigned)stage, success?"ok":s_reason,
               (unsigned)s_http_status, (unsigned)s_used, (unsigned)s_expected,
               (unsigned)s_tx_frames, (unsigned)s_ack_frames,
               (unsigned)s_ack_seen, (unsigned)s_last_id);
}

static void fail(const char *reason)
{
    s_reason=reason;
    finish(false);
}

void agnss_online_reset(void)
{
    if(s_phase!=IDLE)fail("reset");
    s_attempted=false;s_done=false;s_phase=IDLE;
}
bool agnss_online_has_injected(void) { return s_done; }

static bool key(const char *line,const char *name)
{
    while(*name) {
        char c=*line++;
        if(c>='A' && c<='Z')c+='a'-'A';
        if(c!=*name++)return false;
    }
    return true;
}

static bool parse_header(char *p)
{
    char *line=strstr(p,"\r\n");bool found=false;
    if(!strncmp(p,"HTTP/1.",7) && (p[7]=='0' || p[7]=='1') && p[8]==' ' &&
       p[9]>='0' && p[9]<='9' && p[10]>='0' && p[10]<='9' &&
       p[11]>='0' && p[11]<='9')
        s_http_status=(uint16_t)((p[9]-'0')*100+(p[10]-'0')*10+p[11]-'0');
    if(!line || (strncmp(p,"HTTP/1.1 200 ",13) && strncmp(p,"HTTP/1.0 200 ",13)))return false;
    line+=2;
    while(*line && *line!='\r') {
        char *end=strstr(line,"\r\n");
        if(!end)return false;
        if(key(line,"transfer-encoding:") || key(line,"content-encoding:"))return false;
        if(key(line,"content-length:")) {
            char *v=line+15;unsigned n=0,digits=0;
            if(found)return false;
            while(v<end && (*v==' ' || *v=='\t'))v++;
            while(v<end && *v>='0' && *v<='9') {
                n=n*10U+(unsigned)(*v++-'0');digits++;
                if(n>AGNSS_STREAM_WORKSPACE_CAPACITY)return false;
            }
            while(v<end && (*v==' ' || *v=='\t'))v++;
            if(v!=end || !digits || !n)return false;
            s_expected=(uint16_t)n;found=true;
        }
        line=end+2;
    }
    return found;
}

/* Receive callback does no modem transaction, UART TX, NOR IO or retries. */
void agnss_online_rx(uint8_t ch,const uint8_t *data,uint16_t n)
{
    uint8_t *b;
    if(ch!=EC800M_CH_AGPS || !data || !n)return;
    if(s_phase==VALIDATING || s_phase==COLD_START || s_phase==COLD_SETTLE || s_phase==SENDING || s_phase==WAIT_ACK){s_reason="late-data";s_phase=FAILED;return;}
    if(s_phase!=RECEIVING)return;
    b=buffer();
    if(!b || n>AGNSS_STREAM_WORKSPACE_CAPACITY-s_used){s_reason="rx-overflow";s_phase=FAILED;return;}
    memcpy(b+s_used,data,n);s_used+=n;
    if(!s_header) {
        unsigned i;
        for(i=3;i<s_used && i<512U;i++) {
            if(b[i-3]=='\r' && b[i-2]=='\n' && b[i-1]=='\r' && b[i]=='\n') {
                /* Temporarily terminate inside the final empty line. */
                b[i]=0;
                if(!parse_header((char*)b)){s_reason="http-header";s_phase=FAILED;return;}
                i++;s_used-=(uint16_t)i;memmove(b,b+i,s_used);s_header=true;break;
            }
            if(b[i]==0){s_reason="http-header";s_phase=FAILED;return;}
        }
        if(!s_header && s_used>=512U){s_reason="header-limit";s_phase=FAILED;}
    }
    if(s_header) {
        if(s_used>s_expected){s_reason="body-overrun";s_phase=FAILED;}
        else if(s_used==s_expected){s_offset=0;s_phase=VALIDATING;}
    }
}

static bool send_get(void) __attribute__((noinline));
static bool send_get(void)
{
    const device_config_t *c=cfg_get();
    const char *host=endpoint_host();
    char req[224];
    if(!host)return false;
    int n=snprintf(req,sizeof req,"GET /download/ephemeris/HD_BDS.hdb HTTP/1.1\r\nHost: %s:%u\r\nConnection: close\r\n\r\n",host,c->agps_port?c->agps_port:80);
    if(n<0 || (size_t)n>=sizeof req)return false;
    /* Set receiving before send: a response may arrive inside the bounded AT wait. */
    s_phase=RECEIVING;
    return ec800m_tcp_send(EC800M_CH_AGPS,(const uint8_t*)req,(uint16_t)n)==0;
}

static int send_gnss(const uint8_t *p,uint16_t n) { return gps_send_raw(p,n); }

static uint16_t build_local_frame(uint8_t id, const uint8_t *payload,
                                  uint16_t payload_len)
{
    uint8_t a=0,b=0;
    uint16_t total=(uint16_t)(payload_len+8U);
    if (!payload || payload_len>sizeof s_local_frame-8U) return 0;
    s_local_frame[0]=0xf1;s_local_frame[1]=0xd9;
    s_local_frame[2]=0x0b;s_local_frame[3]=id;
    s_local_frame[4]=(uint8_t)payload_len;
    s_local_frame[5]=(uint8_t)(payload_len>>8);
    memcpy(s_local_frame+6,payload,payload_len);
    for(uint16_t i=2;i<total-2U;i++){a=(uint8_t)(a+s_local_frame[i]);b=(uint8_t)(b+a);}
    s_local_frame[total-2U]=a;s_local_frame[total-1U]=b;
    return total;
}

static bool build_local_aid(void)
{
    gps_data_t data;
    uint8_t payload[20]={0};
    if (s_local_stage==LOCAL_TIME) {
        gps_get_unfixed_report(&data);
        if (data.year>=2000U && data.year<=2099U && data.month>=1U && data.month<=12U &&
            data.day>=1U && data.day<=31U && data.hour<=23U && data.minute<=59U &&
            data.second<=59U) {
            payload[2]=18U; payload[3]=(uint8_t)data.year; payload[4]=(uint8_t)(data.year>>8);
            payload[5]=data.month; payload[6]=data.day; payload[7]=data.hour;
            payload[8]=data.minute; payload[9]=data.second;
            s_local_len=build_local_frame(0x11,payload,sizeof payload);
            return s_local_len!=0;
        }
        s_local_stage=LOCAL_POS;
    }
    if (s_local_stage==LOCAL_POS) {
        const gps_data_t *g=gps_get_data();
        int32_t lat,lon,alt;
        double scaled;
        if (!g || !g->valid || g->lat < -90.0 || g->lat > 90.0 ||
            g->lon < -180.0 || g->lon > 180.0 || g->altitude_m < -1000.0f ||
            g->altitude_m > 100000.0f) { s_local_stage=NETWORK_DATA; return false; }
        uint8_t pos[17]={0};
        scaled=g->lat*10000000.0; lat=(int32_t)(scaled+(scaled>=0.0?0.5:-0.5));
        scaled=g->lon*10000000.0; lon=(int32_t)(scaled+(scaled>=0.0?0.5:-0.5));
        scaled=(double)g->altitude_m*100.0; alt=(int32_t)(scaled+(scaled>=0.0?0.5:-0.5));
        pos[0]=1U;
        for(uint8_t i=0;i<4;i++){pos[1+i]=(uint8_t)((uint32_t)lat>>(8U*i));pos[5+i]=(uint8_t)((uint32_t)lon>>(8U*i));pos[9+i]=(uint8_t)((uint32_t)alt>>(8U*i));}
        s_local_len=build_local_frame(0x10,pos,sizeof pos);
        return s_local_len!=0;
    }
    return false;
}

static bool send_cold_start(void)
{
    static const uint8_t frame[] = {0xF1,0xD9,0x06,0x40,0x01,0x00,0x01,0x48,0x22};
    return gps_send_raw(frame,sizeof frame) == 0;
}

bool agnss_online_process(gnss_type_t type)
{
    uint32_t now=TICK_MS();
    const device_config_t *c=cfg_get();
    if(type!=GNSS_TYPE_TAU804M || !c->agps_en || fota_is_active() ||
       !ec800m_is_ready() || !gps_is_enabled()) {
        if(s_phase!=IDLE)fail("stopped");
        return true;
    }
    if(s_phase==IDLE) {
        if(gps_is_valid())return true;
        if(s_attempted && (uint32_t)(now-s_epoch)<(s_done?7200000UL:60000UL))return s_done;
        const char *host=endpoint_host();
        if(!host)return true;
        if(!agnss_stream_workspace_try_acquire(AGNSS_STREAM_OWNER_ONLINE))return false;
        s_header=false;s_used=s_expected=s_offset=0;
        s_local_stage=LOCAL_TIME;s_local_len=0;
        s_http_status=s_tx_frames=s_ack_frames=s_ack_seen=0;s_last_id=0;s_reason="unknown";
        s_trace_ack_seen=false;s_trace_cold_ms=s_trace_tx_ms=s_trace_rx_ms=0;
        s_trace_tx_len=0;
        s_epoch=now;s_phase=OPENING;s_socket=true;
        if(ec800m_tcp_open(EC800M_CH_AGPS,host,c->agps_port?c->agps_port:80)!=0)fail("open");
        return true;
    }
    if(s_phase==FAILED){finish(false);return true;}
    if((uint32_t)(now-s_epoch)>=30000UL){fail("deadline");return true;}
    if(s_phase==OPENING) {
        tcp_state_t state=ec800m_tcp_state(EC800M_CH_AGPS);
        if(state==TCP_STATE_OPEN){if(!send_get())fail("http-send");}
        else if(state==TCP_STATE_ERROR || state==TCP_STATE_CLOSED)fail("open");
    } else if(s_phase==RECEIVING) {
        if(ec800m_tcp_state(EC800M_CH_AGPS)!=TCP_STATE_OPEN)fail("socket");
    } else if(s_phase==VALIDATING) {
        uint8_t *b=buffer();
        uint32_t left=(uint32_t)s_expected-s_offset;
        if(left<8U){fail("frame");return true;}
        uint32_t n=(uint32_t)b[s_offset+4]+((uint32_t)b[s_offset+5]<<8)+8U;
        if(n>left || !huada_aid_frame_valid(b+s_offset,(uint16_t)n) ||
           b[s_offset+3]!=0x33){fail("frame");return true;}
        s_offset+=(uint16_t)n;
        if(s_offset==s_expected){s_offset=0;s_phase=COLD_START;}
    } else if (s_phase==COLD_START) {
        if(!send_cold_start())fail("cold-start");
        else {
            /* gps_send_raw returns after UART TX completes; do not count TX time. */
            s_trace_cold_ms=TICK_MS();
            s_phase=COLD_SETTLE;
        }
    } else if(s_phase==COLD_SETTLE) {
        /* Nonblocking: the main loop continues servicing modem/GNSS/watchdog. */
        if((uint32_t)(now-s_trace_cold_ms)>=HUADA_COLD_SETTLE_MS) s_phase=SENDING;
    } else if(s_phase==SENDING) {
        const uint8_t *b;
        uint16_t frame;
        if (s_local_stage!=NETWORK_DATA && !s_local_len) (void)build_local_aid();
        if (s_local_stage!=NETWORK_DATA && s_local_len) {
            b=s_local_frame; frame=s_local_len;
        } else {
            b=buffer()+s_offset;
            frame=(uint16_t)((uint16_t)b[4]+((uint16_t)b[5]<<8)+8U);
        }
        s_ack_sequence=gps_agnss_ack_sequence();
        if (s_tx_frames == 0U) s_trace_tx_ms=now;
        if (s_tx_frames == 0U) s_trace_tx_len=frame;
        s_last_id=b[3];++s_tx_frames;
        if(!huada_ack_start(&s_ack,b,frame,now,1000U,send_gnss))fail("uart");
        else s_phase=WAIT_ACK;
    } else if(s_phase==WAIT_ACK) {
        uint8_t ack[10];
        if(gps_agnss_take_ack(&s_ack_sequence,ack)){
            ++s_ack_seen;
            memcpy(s_trace_ack,ack,sizeof s_trace_ack);
            s_trace_ack_seen=true;s_trace_rx_ms=now;
            huada_ack_receive(&s_ack,ack,10,now);
        }
        huada_ack_poll(&s_ack,now);
        if(s_ack.state==HUADA_ACK_OK) {
            ++s_ack_frames;
            if (s_local_stage!=NETWORK_DATA) {
                s_local_len=0;
                if (s_local_stage==LOCAL_TIME) s_local_stage=LOCAL_POS;
                else s_local_stage=NETWORK_DATA;
                s_phase=SENDING;
            } else {
                uint8_t *b=buffer()+s_offset;
                s_offset+=(uint16_t)((uint16_t)b[4]+((uint16_t)b[5]<<8)+8U);
                if(s_offset==s_expected)finish(true);
                else s_phase=SENDING;
            }
        } else if(s_ack.state!=HUADA_ACK_WAIT)
            fail(s_ack.state==HUADA_ACK_TIMEOUT?"ack-timeout":
                 s_ack.state==HUADA_ACK_NAK?"ack-nak":"ack-other");
    }
    return true;
}
