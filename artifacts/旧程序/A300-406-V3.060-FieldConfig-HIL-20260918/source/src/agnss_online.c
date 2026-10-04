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
#include <string.h>

enum { IDLE, OPENING, RECEIVING, VALIDATING, SENDING, WAIT_ACK, FAILED };
static uint8_t s_phase;
static bool s_header, s_done, s_attempted, s_socket;
static uint16_t s_used, s_expected, s_offset;
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

static void finish(bool success)
{
    bool close = s_socket;
    s_socket=false;s_phase=IDLE;s_epoch=TICK_MS();s_attempted=true;
    s_done=success;
    huada_ack_cancel(&s_ack);
    agnss_stream_workspace_release(AGNSS_STREAM_OWNER_ONLINE);
    if(close)ec800m_tcp_close(EC800M_CH_AGPS);
    dbg_printf("[AGNSS] result=%u\r\n",success?1U:0U);
}

void agnss_online_reset(void)
{
    if(s_phase!=IDLE)finish(false);
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
    if(s_phase==VALIDATING || s_phase==SENDING || s_phase==WAIT_ACK){s_phase=FAILED;return;}
    if(s_phase!=RECEIVING)return;
    b=buffer();
    if(!b || n>AGNSS_STREAM_WORKSPACE_CAPACITY-s_used){s_phase=FAILED;return;}
    memcpy(b+s_used,data,n);s_used+=n;
    if(!s_header) {
        unsigned i;
        for(i=3;i<s_used && i<512U;i++) {
            if(b[i-3]=='\r' && b[i-2]=='\n' && b[i-1]=='\r' && b[i]=='\n') {
                /* Temporarily terminate inside the final empty line. */
                b[i]=0;
                if(!parse_header((char*)b)){s_phase=FAILED;return;}
                i++;s_used-=(uint16_t)i;memmove(b,b+i,s_used);s_header=true;break;
            }
            if(b[i]==0){s_phase=FAILED;return;}
        }
        if(!s_header && s_used>=512U)s_phase=FAILED;
    }
    if(s_header) {
        if(s_used>s_expected)s_phase=FAILED;
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

bool agnss_online_process(gnss_type_t type)
{
    uint32_t now=TICK_MS();
    const device_config_t *c=cfg_get();
    if(type!=GNSS_TYPE_TAU804M || !c->agps_en || fota_is_active() ||
       !ec800m_is_ready() || !gps_is_enabled()) {
        if(s_phase!=IDLE)finish(false);
        return true;
    }
    if(s_phase==IDLE) {
        if(gps_is_valid())return true;
        if(s_attempted && (uint32_t)(now-s_epoch)<(s_done?7200000UL:60000UL))return s_done;
        const char *host=endpoint_host();
        if(!host)return true;
        if(!agnss_stream_workspace_try_acquire(AGNSS_STREAM_OWNER_ONLINE))return false;
        s_header=false;s_used=s_expected=s_offset=0;s_epoch=now;s_phase=OPENING;s_socket=true;
        if(ec800m_tcp_open(EC800M_CH_AGPS,host,c->agps_port?c->agps_port:80)!=0)finish(false);
        return true;
    }
    if(s_phase==FAILED || (uint32_t)(now-s_epoch)>=30000UL){finish(false);return true;}
    if(s_phase==OPENING) {
        tcp_state_t state=ec800m_tcp_state(EC800M_CH_AGPS);
        if(state==TCP_STATE_OPEN){if(!send_get())finish(false);}
        else if(state==TCP_STATE_ERROR || state==TCP_STATE_CLOSED)finish(false);
    } else if(s_phase==RECEIVING) {
        if(ec800m_tcp_state(EC800M_CH_AGPS)!=TCP_STATE_OPEN)finish(false);
    } else if(s_phase==VALIDATING) {
        uint8_t *b=buffer();
        uint32_t left=(uint32_t)s_expected-s_offset;
        if(left<8U){finish(false);return true;}
        uint32_t n=(uint32_t)b[s_offset+4]+((uint32_t)b[s_offset+5]<<8)+8U;
        if(n>left || !huada_aid_frame_valid(b+s_offset,(uint16_t)n) ||
           (b[s_offset+3]!=0x32 && b[s_offset+3]!=0x33)){finish(false);return true;}
        s_offset+=(uint16_t)n;
        if(s_offset==s_expected){s_offset=0;s_phase=SENDING;}
    } else if(s_phase==SENDING) {
        uint8_t *b=buffer()+s_offset;
        uint16_t frame=(uint16_t)((uint16_t)b[4]+((uint16_t)b[5]<<8)+8U);
        s_ack_sequence=gps_agnss_ack_sequence();
        if(!huada_ack_start(&s_ack,b,frame,now,1000U,send_gnss))finish(false);
        else s_phase=WAIT_ACK;
    } else if(s_phase==WAIT_ACK) {
        uint8_t ack[10];
        if(gps_agnss_take_ack(&s_ack_sequence,ack))huada_ack_receive(&s_ack,ack,10,now);
        huada_ack_poll(&s_ack,now);
        if(s_ack.state==HUADA_ACK_OK) {
            uint8_t *b=buffer()+s_offset;
            s_offset+=(uint16_t)((uint16_t)b[4]+((uint16_t)b[5]<<8)+8U);
            if(s_offset==s_expected)finish(true);
            else s_phase=SENDING;
        } else if(s_ack.state!=HUADA_ACK_WAIT)finish(false);
    }
    return true;
}
