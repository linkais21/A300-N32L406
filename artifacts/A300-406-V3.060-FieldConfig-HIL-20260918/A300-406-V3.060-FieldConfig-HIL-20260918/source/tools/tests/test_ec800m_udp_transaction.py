"""Execute production UDP state machine with scripted modem events and owners."""
from pathlib import Path
import shutil, subprocess, tempfile
ROOT=Path(__file__).resolve().parents[2]
PRE=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define EC800M_CH_OTA 1
#define EC800M_CH_MAX 4
#define AT_RESP_MAX 2048
#define TICK_MS() tick
static uint32_t tick;
enum {TCP_STATE_CLOSED,TCP_STATE_OPENING,TCP_STATE_OPEN,TCP_STATE_ERROR};
static struct {int state;} s_tcp[4];
static uint32_t s_tcp_generation[4];
static uint8_t s_tcp_qird_pending_mask;
enum {AT_OWNER_NONE,AT_OWNER_TCP};static int s_at_owner;
static bool ready=true,tx_ok=true,read_ok=true;
static char last_command[160]; static unsigned sends,reads;
typedef struct {int unused;} ec800m_qird_diag_t;
static bool ec800m_is_ready(void){return ready;}
static bool at_owner_acquire(int o){if(s_at_owner)return false;s_at_owner=o;return true;}
static void at_owner_release(int o){if(s_at_owner==o)s_at_owner=0;}
static bool usart_send_str(const char *s){if(strcmp(s,"\r\n"))strcpy(last_command,s);return tx_ok;}
static bool usart_send_buf(const uint8_t *p,uint16_t n){(void)p;(void)n;++sends;return tx_ok;}
static void drain_rx(void){}
static void IWDG_ReloadKey(void){++tick;}
static void ec800m_wait_service_hook(void){}
static bool qird_collect_payload(uint8_t c,uint16_t n,const uint8_t **p,
 uint16_t *len,ec800m_qird_diag_t *d,uint32_t t){
 static const uint8_t data[]={0x66,0,13,10,0xff};
 assert(c==1&&n>=sizeof data&&t<=2000&&s_at_owner==0);(void)d;
 ++reads;*p=data;*len=sizeof data;return read_ok;
}
int ec800m_udp_txn_start(const char*,uint16_t,const uint8_t*,uint16_t,uint8_t*,uint16_t,uint32_t);
void ec800m_udp_txn_process(void);
int ec800m_udp_txn_result(void);
int ec800m_udp_txn(const char*,uint16_t,const uint8_t*,uint16_t,uint8_t*,uint16_t,uint32_t);
'''
POST=r'''
static uint8_t tx[16],rx[64];
static void begin(void){
 assert(ec800m_udp_txn_start("test.example",10004,tx,sizeof tx,rx,sizeof rx,8000)==0);
 assert(ec800m_udp_txn_start("x",1,tx,16,rx,64,8000)==-2);
 ec800m_udp_txn_process();assert(strstr(last_command,"QIOPEN")&&s_at_owner==AT_OWNER_TCP);
 assert(ec800m_udp_txn_result()==-2);
}
static void opened(void){
 s_udp.cmd_ok=true;ec800m_udp_txn_process();assert(!strstr(last_command,"QISEND"));
 s_udp.open_urc=true;ec800m_udp_txn_process();ec800m_udp_txn_process();
 assert(strstr(last_command,"QISEND"));s_udp.prompt=true;
 ec800m_udp_txn_process();assert(sends);s_udp.cmd_ok=true;ec800m_udp_txn_process();
}
static int close_result(void){
 for(unsigned i=0;i<4;i++) {ec800m_udp_txn_process();if(strstr(last_command,"QICLOSE"))s_udp.cmd_ok=true;}
 int r=ec800m_udp_txn_result();assert(r!=-2&&s_at_owner==0&&s_tcp[1].state==TCP_STATE_CLOSED);return r;
}
int main(void){
 begin();opened();assert(reads==0);s_udp.recv_urc=true;ec800m_udp_txn_process();
 assert(close_result()==5&&!memcmp(rx,(uint8_t[]){0x66,0,13,10,0xff},5));
 begin();tick+=6000;ec800m_udp_txn_process();assert(close_result()<0);
 begin();opened();tick+=8001;ec800m_udp_txn_process();assert(close_result()==0);
 begin();s_udp.cmd_error=true;ec800m_udp_txn_process();assert(close_result()<0);
 s_tcp[1].state=TCP_STATE_OPEN;assert(ec800m_udp_txn_start("x",1,tx,16,rx,64,8000)<0);
 assert(s_tcp[1].state==TCP_STATE_OPEN);s_tcp[1].state=TCP_STATE_CLOSED;
 begin();opened();read_ok=false;s_udp.recv_urc=true;ec800m_udp_txn_process();assert(close_result()<0);
 read_ok=true;begin();opened();s_udp.recv_urc=true;ec800m_udp_txn_process();assert(close_result()==5);
 assert(ec800m_udp_txn_start("x",1,tx,16,rx,64,0)<0);
 assert(ec800m_udp_txn_start("x",1,tx,16,rx,65535,8000)<0);
 return 0;
}
'''
def main():
    c=(ROOT/'src/ec800m.c').read_text(encoding='utf-8')
    a=c.index('typedef enum {\n    UDP_TXN_IDLE')
    state=c[a:c.index('/* Upper-layer receive callback */',a)]
    a=c.index('int ec800m_udp_send_once(')
    code=c[a:c.index('void ec800m_tcp_close(',a)]
    with tempfile.TemporaryDirectory() as td:
        p=Path(td);(p/'h.c').write_text(PRE+state+code+POST)
        subprocess.run([shutil.which('gcc'),'-std=c99','-Wall','-Wextra',
                        str(p/'h.c'),'-o',str(p/'h.exe')],check=True)
        subprocess.run([str(p/'h.exe')],check=True,timeout=10)
    print('UDP production transaction: PASS')
if __name__=='__main__':main()
