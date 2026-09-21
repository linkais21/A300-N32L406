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
            'gps.h': '#include <stdint.h>\n#include <stdbool.h>\nbool gps_is_valid(void);bool gps_is_enabled(void);int gps_send_raw(const uint8_t*,uint32_t);uint32_t gps_agnss_ack_sequence(void);bool gps_agnss_take_ack(uint32_t*,uint8_t*);\n',
            'debug_uart.h': 'void dbg_printf(const char*,...);\n',
        }
        for name, text in headers.items():
            (p / name).write_text(text, encoding='ascii')
        (p / 'test.c').write_text(r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "agnss_online.h"
#include "flash_config.h"
#include "ec800m.h"
#include "fota.h"
uint32_t tick;
static device_config_t cfg={1,"",0};
static tcp_state_t tcp;
static bool ready=true,enabled=true,fix,ota;
static unsigned opens,sends,closes,uart,acks;
static uint8_t response[600],packet[100],ack[10];
static int tx_error;
static char request[256];
device_config_t *cfg_get(void){return &cfg;}
bool ec800m_is_ready(void){return ready;}
bool gps_is_valid(void){return fix;}
bool gps_is_enabled(void){return enabled;}
fota_state_t fota_get_state(void){return ota?FOTA_STATE_DOWNLOADING:FOTA_STATE_IDLE;}
void dbg_printf(const char *f,...){(void)f;}
int ec800m_tcp_open(uint8_t ch,const char *host,uint16_t port){assert(ch==2&&host&&port==80);opens++;tcp=TCP_STATE_OPENING;return 0;}
int ec800m_tcp_send(uint8_t ch,const uint8_t *p,uint16_t n){assert(ch==2&&n<sizeof request);memcpy(request,p,n);request[n]=0;sends++;return 0;}
void ec800m_tcp_close(uint8_t ch){assert(ch==2);closes++;tcp=TCP_STATE_CLOSED;}
tcp_state_t ec800m_tcp_state(uint8_t ch){assert(ch==2);return tcp;}
int gps_send_raw(const uint8_t *p,uint32_t n){assert(n==100&&!memcmp(p,packet,n));uart++;return tx_error;}
uint32_t gps_agnss_ack_sequence(void){return acks;}
bool gps_agnss_take_ack(uint32_t *seq,uint8_t *p){if(*seq==acks)return false;*seq=acks;memcpy(p,ack,10);return true;}
static void sum(uint8_t *p,unsigned n){uint8_t a=0,b=0;for(unsigned i=2;i<n-2;i++){a+=p[i];b+=a;}p[n-2]=a;p[n-1]=b;}
static void start(void){agnss_online_reset();cfg.agps_en=1;tick+=60001;fix=ota=false;ready=enabled=true;tx_error=0;assert(agnss_online_process(GNSS_TYPE_TAU804M));tcp=TCP_STATE_OPEN;assert(agnss_online_process(GNSS_TYPE_TAU804M));assert(strstr(request,"GET /download/ephemeris/HD_BDS.hdb HTTP/1.1\r\n"));}
static void pump(unsigned n){while(n--)agnss_online_process(GNSS_TYPE_TAU804M);}
int main(void){
    memcpy(packet,"\xf1\xd9\x0b\x33\x5c\x00",6);sum(packet,100);
    memcpy(ack,"\xf1\xd9\x05\x01\x02\x00\x0b\x33",8);sum(ack,10);
    const char *head="HTTP/1.1 200 OK\r\nContent-Length: 200\r\n\r\n";
    size_t h=strlen(head);memcpy(response,head,h);memcpy(response+h,packet,100);memcpy(response+h+100,packet,100);
    /* Every split including between CR/LF, binary header and checksum. */
    for(unsigned split=1;split<h+200;split++){
        start();unsigned before=uart;
        agnss_online_rx(2,response,split);agnss_online_rx(2,response+split,h+200-split);
        pump(5);assert(uart==before+1);pump(4);assert(uart==before+1);
        acks++;pump(3);assert(uart==before+2);acks++;pump(4);
        assert(agnss_online_has_injected());
    }
    start();agnss_online_rx(2,response,h+200);pump(5);unsigned before=uart;
    tick+=1000;pump(3);assert(!agnss_online_has_injected()&&uart==before);
    acks++;pump(3);assert(uart==before); /* late ACK does not restart */
    start();agnss_online_rx(2,response,h+200);pump(5);ota=true;pump(1);
    assert(tcp==TCP_STATE_CLOSED&&!agnss_online_has_injected());ota=false;
    start();agnss_online_rx(2,response,h+199);tick+=30000;pump(1);
    assert(tcp==TCP_STATE_CLOSED&&!agnss_online_has_injected());
    const char *bad[]={"HTTP/1.1 404 Bad\r\nContent-Length: 1\r\n\r\nx",
      "HTTP/1.1 200 OK\r\nContent-Length: 99999\r\n\r\n",
      "HTTP/1.1 200 OK\r\nContent-Length: 100\r\nContent-Length: 100\r\n\r\n",
      "HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nContent-Length: 100\r\n\r\n"};
    for(unsigned i=0;i<sizeof bad/sizeof bad[0];i++){start();before=uart;agnss_online_rx(2,(const uint8_t*)bad[i],strlen(bad[i]));pump(6);assert(uart==before&&!agnss_online_has_injected());}
    start();response[h+199]^=1;before=uart;agnss_online_rx(2,response,h+200);pump(6);assert(uart==before);response[h+199]^=1;
    start();tx_error=-1;agnss_online_rx(2,response,h+200);pump(6);assert(!agnss_online_has_injected());
    start();agnss_online_rx(2,response,h+200);agnss_online_rx(2,(const uint8_t*)"x",1);before=uart;pump(6);assert(uart==before);
    start();agnss_online_rx(2,response,h+200);pump(5);ack[3]=0;sum(ack,10);acks++;pump(3);assert(!agnss_online_has_injected());ack[3]=1;sum(ack,10);
    start();agnss_online_rx(2,response,h+200);pump(5);enabled=false;pump(1);assert(tcp==TCP_STATE_CLOSED);enabled=true;
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
