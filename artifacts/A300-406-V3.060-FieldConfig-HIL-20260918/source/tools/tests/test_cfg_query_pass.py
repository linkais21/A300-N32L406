"""Production cfg_query frames, identity, Pass normalization and confirmations."""
from pathlib import Path
import shutil, subprocess, tempfile

ROOT = Path(__file__).resolve().parents[2]
HARNESS = r'''
#include <assert.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include "cfg_query.h"
#include "service_workspace.h"
static uint8_t *rx; static const uint8_t *tx;
static unsigned sent, executed, starts;
static int received, confirm_result; static bool execute_ok=true;
static const uint8_t id[]={0x01,0x23,0x45,0x67,0x89,0x01,0x23,0x45};
uint32_t g_tick_ms;
void *cfg_get(void){return 0;}
void work_mode_config_changed(void *p,uint32_t t){(void)p;(void)t;}
int dbg_printf(const char *f, ...){(void)f;return 0;}
bool ec800m_is_ready(void){return true;}
void ec800m_get_imei(char *p,unsigned n){assert(n>=16);memcpy(p,"123456789012345",16);}
bool at_config_execute_text_command(const uint8_t *p,uint16_t n){
 ++executed;assert(n==7&&!memcmp(p,"hbt,120",7));return execute_ok;
}
int ec800m_udp_txn_start(const char *h,uint16_t port,const uint8_t *p,uint16_t n,
 uint8_t *r,uint16_t cap,uint32_t timeout){
 (void)h;assert(port==10004&&n==16&&cap>=128&&timeout==8000);
 assert(!memcmp(p+5,id,8));assert(p[2]==0x13);tx=p;rx=r;++starts;return 0;
}
void ec800m_udp_txn_process(void){}
int ec800m_udp_txn_result(void){return received;}
int ec800m_udp_send_once(const char *h,uint16_t port,const uint8_t *p,uint16_t n){
 (void)h;assert(port==10004&&n==16&&p[2]==0x14&&!memcmp(p+5,id,8));
 uint8_t c=0;for(unsigned i=0;i<14;i++)c^=p[i];assert(p[14]==c);++sent;return confirm_result;
}
static void finish_frame(unsigned n){
 rx[3]=(n-7)>>8;rx[4]=n-7;rx[n-2]=0;
 for(unsigned i=0;i<n-2;i++)rx[n-2]^=rx[i];rx[n-1]=13;received=n;
}
static void begin(const char *command){
 cfg_query_init();sent=executed=starts=0;confirm_result=0;execute_ok=true;
 assert(cfg_query_start()==0);cfg_query_process();assert(starts==1);
 memcpy(rx,tx,16);rx[2]=0x92;
 if(!command){rx[13]=0;finish_frame(16);return;}
 unsigned n=strlen(command);rx[13]=1;rx[14]=3;memset(rx+15,0,10);
 memcpy(rx+15,"Pass",4);rx[25]=n;memcpy(rx+26,command,n);finish_frame(28+n);
}
static void end(int expected,unsigned calls,unsigned acks){
 cfg_query_process();int result=99;assert(cfg_query_take_result(&result));
 assert(result==expected&&executed==calls&&sent==acks);
 assert(service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_OTA));
 service_workspace_release(SERVICE_WORKSPACE_OWNER_OTA);
}
int main(void){
 begin(NULL);end(0,0,0);
 begin("hbt,120#");end(0,1,1);
 begin("hbt,120");end(0,1,1);
 begin("\"hbt,120#\"");end(0,1,1);
 begin("hbt,120#");rx[19]='x';finish_frame(received);end(-1,0,0);
 begin("hbt,120#");rx[13]=2;finish_frame(received);end(-1,0,0);
 begin("hbt,120#");rx[25]--;finish_frame(received);end(-1,0,0);
 begin("hbt,120#");rx[5]^=1;finish_frame(received);end(-1,0,0);
 begin("hbt,120#");rx[received-2]^=1;end(-1,0,0);
 begin("hbt,120#");execute_ok=false;end(-1,1,0);
 begin("hbt,120#");confirm_result=-1;end(-1,1,1);
 return 0;
}
'''
def main():
    with tempfile.TemporaryDirectory() as td:
        p=Path(td)
        (p/'h.c').write_text(HARNESS)
        (p/'n32l40x.h').write_text('#pragma once\n')
        (p/'at_config.h').write_text('#include <stdint.h>\n#include <stdbool.h>\nbool at_config_execute_text_command(const uint8_t*,uint16_t);\n')
        subprocess.run([shutil.which('gcc'),'-std=c99','-Wall','-Wextra','-Werror',
            '-Wno-misleading-indentation','-I',str(p),'-I',str(ROOT/'include'),
            str(p/'h.c'),str(ROOT/'src/cfg_query.c'),str(ROOT/'src/service_workspace.c'),
            '-o',str(p/'test.exe')],check=True)
        subprocess.run([str(p/'test.exe')],check=True)
    print('cfg query Pass: PASS (11 scenarios)')
if __name__=='__main__':main()
