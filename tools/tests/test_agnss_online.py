"""Exercise the actual Huada HTTP/download/ACK state machine without hardware."""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def test_online():
    with tempfile.TemporaryDirectory(prefix='agnss_online_') as td:
        p = Path(td)
        headers = {
            'config.h': '#include <stdint.h>\nextern uint32_t tick;\n#define TICK_MS() tick\n',
            'flash_config.h': 'typedef struct {unsigned char agps_en;char agps_ip[64];unsigned short agps_port;} device_config_t;\ndevice_config_t *cfg_get(void);\n',
            'gps.h': '#include <stdint.h>\n#include <stdbool.h>\ntypedef struct { double lat,lon; float altitude_m; uint16_t year; uint8_t month,day,hour,minute,second; bool valid; } gps_data_t; typedef gps_data_t gps_context_t;\nbool gps_is_valid(void);bool gps_is_enabled(void);int gps_send_raw(const uint8_t*,uint32_t);uint32_t gps_agnss_ack_sequence(void);bool gps_agnss_take_ack(uint32_t*,uint8_t*);const gps_data_t *gps_get_data(void);void gps_get_unfixed_report(gps_data_t*);\n',
            'debug_uart.h': 'void dbg_printf(const char*,...);void dbg_putchar(char);\n',
        }
        for name, text in headers.items():
            (p / name).write_text(text, encoding='ascii')
        (p / 'test.c').write_text(r'''
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include "agnss_online.h"
#include "flash_config.h"
#include "ec800m.h"
#include "fota.h"
#include "gps.h"
uint32_t tick;
static device_config_t cfg={1,"",0};
static tcp_state_t tcp;
static bool ready=true,enabled=true,fix,ota;
static gps_data_t gps={0};
static unsigned opens,sends,closes,uart,acks;
static uint8_t response[600],packet[100],ack[10];
static uint8_t last_id;
static void sum(uint8_t *p,unsigned n);
static int tx_error;
static uint32_t cold_done;
static char request[256];
static char last_log[192];
static char trace_hex[1100];
static unsigned trace_used;
static unsigned timing_lines, tx_lines, rx_lines;
device_config_t *cfg_get(void){return &cfg;}
bool ec800m_is_ready(void){return ready;}
bool gps_is_valid(void){return fix;}
bool gps_is_enabled(void){return enabled;}
const gps_data_t *gps_get_data(void){return &gps;}
void gps_get_unfixed_report(gps_data_t *out){*out=gps;}
fota_state_t fota_get_state(void){return ota?FOTA_STATE_DOWNLOADING:FOTA_STATE_IDLE;}
void dbg_printf(const char *f,...){
    va_list args;va_start(args,f);vsnprintf(last_log,sizeof last_log,f,args);va_end(args);
    if(strstr(last_log,"[AGNSS-RAW]"))timing_lines++;
    if(strstr(last_log,"[AGNSS-TX]"))tx_lines++;
    if(strstr(last_log,"[AGNSS-RX]"))rx_lines++;
}
void dbg_putchar(char c){assert(trace_used+1<sizeof trace_hex);trace_hex[trace_used++]=c;trace_hex[trace_used]=0;}
int ec800m_tcp_open(uint8_t ch,const char *host,uint16_t port){assert(ch==2&&host&&port==80);opens++;tcp=TCP_STATE_OPENING;return 0;}
int ec800m_tcp_send(uint8_t ch,const uint8_t *p,uint16_t n){assert(ch==2&&n<sizeof request);memcpy(request,p,n);request[n]=0;sends++;return 0;}
void ec800m_tcp_close(uint8_t ch){assert(ch==2);closes++;tcp=TCP_STATE_CLOSED;}
tcp_state_t ec800m_tcp_state(uint8_t ch){assert(ch==2);return tcp;}
int gps_send_raw(const uint8_t *p,uint32_t n){
    static const uint8_t cold[]={0xf1,0xd9,0x06,0x40,0x01,0x00,0x01,0x48,0x22};
    if(n==sizeof cold) { assert(!memcmp(p,cold,sizeof cold)); tick+=7; cold_done=tick; }
    else { assert((n==28U && p[3]==0x11U) || (n==25U && p[3]==0x10U) || (n==100U && p[3]==0x33U)); if(n==100U) assert(!memcmp(p,packet,n)); assert((uint32_t)(tick-cold_done)>=1000U); last_id=p[3]; }
    uart++;return tx_error;
}
uint32_t gps_agnss_ack_sequence(void){return acks;}
bool gps_agnss_take_ack(uint32_t *seq,uint8_t *p){if(*seq==acks)return false;*seq=acks;memcpy(p,ack,10);p[7]=last_id;sum(p,10);return true;}
static void sum(uint8_t *p,unsigned n){uint8_t a=0,b=0;for(unsigned i=2;i<n-2;i++){a+=p[i];b+=a;}p[n-2]=a;p[n-1]=b;}
static void start(void){agnss_online_reset();cfg.agps_en=1;tick+=60001;fix=ota=false;ready=enabled=true;tx_error=0;gps=(gps_data_t){.lat=22.5,.lon=113.9,.altitude_m=12.5f,.year=2026,.month=10,.day=1,.hour=12,.minute=30,.second=0,.valid=true};assert(agnss_online_process(GNSS_TYPE_TAU804M));tcp=TCP_STATE_OPEN;assert(agnss_online_process(GNSS_TYPE_TAU804M));assert(strstr(request,"GET /download/ephemeris/HD_BDS.hdb HTTP/1.1\r\n"));}
static void pump(unsigned n){while(n--)agnss_online_process(GNSS_TYPE_TAU804M);}
static void first_aid(void){
    unsigned before=uart;
    pump(3);assert(uart==before+1); /* cold TX consumes seven ms */
    pump(10);assert(uart==before+1);
    tick+=999;pump(3);assert(uart==before+1);
    tick++;pump(2);assert(uart==before+2);
}
int main(void){
    memcpy(packet,"\xf1\xd9\x0b\x33\x5c\x00",6);sum(packet,100);
    memcpy(ack,"\xf1\xd9\x05\x01\x02\x00\x0b\x33",8);sum(ack,10);
    const char *head="HTTP/1.1 200 OK\r\nContent-Length: 200\r\n\r\n";
    size_t h=strlen(head);memcpy(response,head,h);memcpy(response+h,packet,100);memcpy(response+h+100,packet,100);
    /* Every split including between CR/LF, binary header and checksum. */
    for(unsigned split=1;split<h+200;split++){
        start();unsigned before=uart;
        agnss_online_rx(2,response,split);agnss_online_rx(2,response+split,h+200-split);
        first_aid();assert(uart==before+2);pump(4);assert(uart==before+2);
        acks++;pump(1);pump(1);assert(uart==before+3);
        acks++;pump(2);assert(uart==before+4);
        acks++;pump(2);assert(uart==before+5);
        acks++;pump(2);
        assert(agnss_online_has_injected());
    }
    assert(strstr(last_log,"result=1")&&strstr(last_log,"http=200 rx=200/200 tx=4 ack=4 seen=4"));
    start();agnss_online_rx(2,response,h+200);first_aid();unsigned before=uart;
    tick+=1000;pump(3);assert(!agnss_online_has_injected()&&uart==before);
    assert(strstr(last_log,"reason=ack-timeout")&&strstr(last_log,"tx=1 ack=0 seen=0"));
    acks++;pump(3);assert(uart==before); /* late ACK does not restart */
    start();agnss_online_rx(2,response,h+200);first_aid();ota=true;pump(1);
    assert(tcp==TCP_STATE_CLOSED&&!agnss_online_has_injected());ota=false;
    start();agnss_online_rx(2,response,h+199);tick+=30000;pump(1);
    assert(tcp==TCP_STATE_CLOSED&&!agnss_online_has_injected());
    assert(strstr(last_log,"reason=deadline")&&strstr(last_log,"http=200")&&strstr(last_log,"tx=0 ack=0 seen=0"));
    start();tcp=TCP_STATE_CLOSED;pump(1);
    assert(strstr(last_log,"reason=socket")&&strstr(last_log,"http=0 rx=0/0 tx=0 ack=0 seen=0"));
    const char *bad[]={"HTTP/1.1 404 Bad\r\nContent-Length: 1\r\n\r\nx",
      "HTTP/1.1 200 OK\r\nContent-Length: 99999\r\n\r\n",
      "HTTP/1.1 200 OK\r\nContent-Length: 100\r\nContent-Length: 100\r\n\r\n",
      "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nContent-Length: 100\r\n\r\n"};
    for(unsigned i=0;i<sizeof bad/sizeof bad[0];i++){start();before=uart;agnss_online_rx(2,(const uint8_t*)bad[i],strlen(bad[i]));pump(6);assert(uart==before&&!agnss_online_has_injected());}
    assert(strstr(last_log,"reason=http-header"));
    start();before=uart;agnss_online_rx(2,(const uint8_t*)bad[0],strlen(bad[0]));pump(1);
    assert(strstr(last_log,"reason=http-header")&&strstr(last_log,"http=404")&&uart==before);
    start();response[h+199]^=1;before=uart;agnss_online_rx(2,response,h+200);pump(6);assert(uart==before);response[h+199]^=1;
    start();tx_error=-1;agnss_online_rx(2,response,h+200);pump(6);assert(!agnss_online_has_injected());
    assert(strstr(last_log,"reason=cold-start")&&strstr(last_log,"tx=0 ack=0 seen=0"));
    start();agnss_online_rx(2,response,h+200);agnss_online_rx(2,(const uint8_t*)"x",1);before=uart;pump(6);assert(uart==before);
    start();agnss_online_rx(2,response,h+200);first_aid();ack[3]=0;sum(ack,10);
    trace_used=timing_lines=tx_lines=rx_lines=0;
    pump(1);assert(trace_used==0 && timing_lines==0 && tx_lines==0 && rx_lines==0);
    acks++;pump(3);assert(!agnss_online_has_injected());ack[3]=1;sum(ack,10);
    assert(strstr(last_log,"reason=ack-nak")&&strstr(last_log,"tx=1 ack=0 seen=1"));
    assert(timing_lines==1 && tx_lines==1 && rx_lines==1);
    assert(trace_used==76 && !memcmp(trace_hex,"f1d90b111400000012ea070a010c1e00",32));
    assert(strstr(trace_hex,"f1d9050002000b11"));
    /* UTC is sampled after settling, never cached before the delay. */
    start();agnss_online_rx(2,response,h+200);pump(3);before=uart;
    tick+=999;gps.second=1;pump(3);assert(uart==before);
    tick++;pump(2);ack[3]=0;sum(ack,10);trace_used=0;
    acks++;pump(2);ack[3]=1;sum(ack,10);
    assert(!memcmp(trace_hex,"f1d90b111400000012ea070a010c1e01",32));
    /* The overall deadline still applies during the settle window. */
    start();agnss_online_rx(2,response,h+200);pump(3);before=uart;
    tick+=30000;pump(2);assert(uart==before && strstr(last_log,"reason=deadline"));
    /* Cold settle survives tick wrap; cancellation and late input stop TX. */
    tick=UINT32_MAX-60101U;start();agnss_online_rx(2,response,h+200);first_aid();
    agnss_online_reset();assert(!agnss_online_has_injected());
    start();agnss_online_rx(2,response,h+200);pump(3);before=uart;
    enabled=false;pump(1);tick+=1000;pump(3);assert(uart==before);enabled=true;
    start();agnss_online_rx(2,response,h+200);pump(3);before=uart;
    agnss_online_rx(2,(const uint8_t*)"x",1);tick+=1000;pump(3);assert(uart==before);
    assert(strstr(last_log,"reason=late-data"));
    /* The TAU804M is configured as BDS-only; a GPS AID-PEPH frame is rejected. */
    { uint8_t gps_packet[73]={0xf1,0xd9,0x0b,0x32,0x41,0x00};
      uint8_t gps_response[160];
      sum(gps_packet,sizeof gps_packet);
      size_t gh=strlen("HTTP/1.1 200 OK\r\nContent-Length: 73\r\n\r\n");
      memcpy(gps_response,"HTTP/1.1 200 OK\r\nContent-Length: 73\r\n\r\n",gh);
      memcpy(gps_response+gh,gps_packet,sizeof gps_packet);
      start();agnss_online_rx(2,gps_response,(uint16_t)(gh+sizeof gps_packet));pump(3);
      assert(!agnss_online_has_injected());
    }
    start();agnss_online_rx(2,response,h+200);first_aid();enabled=false;pump(1);assert(tcp==TCP_STATE_CLOSED);enabled=true;
    agnss_online_reset();fix=true;assert(agnss_online_process(GNSS_TYPE_TAU804M));fix=false;
    memset(cfg.agps_ip,'a',sizeof cfg.agps_ip);before=opens;pump(1);assert(opens==before);cfg.agps_ip[0]=0;
    agnss_online_reset();cfg.agps_en=0;before=opens;pump(10);assert(opens==before);
    puts("AGNSS online: PASS");return 0;
}
''', encoding='ascii')
        cc = shutil.which('gcc') or shutil.which('clang')
        exe = p / 'test.exe'
        subprocess.run([cc, '-std=c99', '-O1', '-Wall', '-Wextra', '-Werror',
                        '-I', str(p), '-I', str(ROOT / 'include'), str(p / 'test.c'),
                        str(ROOT / 'src/agnss_online.c'), str(ROOT / 'src/huada_ack.c'),
                        str(ROOT / 'src/agnss_stream_workspace.c'), '-o', str(exe)], check=True, timeout=60)
        subprocess.run([str(exe)], check=True, timeout=20)


if __name__ == '__main__':
    test_online()
