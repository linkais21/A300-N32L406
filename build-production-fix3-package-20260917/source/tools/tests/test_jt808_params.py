"""Compile actual parameter handlers: transactional writes and wire format."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[2]
HARNESS=r'''
#include <assert.h>
#include <string.h>
#include <stdarg.h>
#include "jt808.h"
#include "jt808_params.h"
#include "flash_config.h"
#include "jt808_terminal_info.h"
#include "work_mode.h"
#include "service_workspace.h"
volatile uint32_t g_tick_ms;
static device_config_t cfg, disk;
static unsigned saves, effects, reconnects, acks;
static bool fail_store;
static uint8_t result, response[1024];
static uint16_t response_len;
device_config_t *cfg_get(void){return &cfg;}
bool cfg_store_candidate(const device_config_t *c){++saves;if(fail_store)return false;disk=cfg=*c;return true;}
void cfg_save(void){++saves;disk=cfg;}
void cfg_set_server(const char *ip,uint16_t port,bool backup){(void)ip;(void)port;(void)backup;++effects;}
void jt808_set_heartbeat_s(uint16_t s){assert(s==cfg.heartbeat_s);++effects;}
void jt808_set_report_interval(uint16_t a,uint16_t b){assert(a==cfg.report_moving_s&&b==cfg.report_stopped_s);++effects;}
void jt808_set_server(const char *s,uint16_t p,bool b){(void)s;(void)p;(void)b;++effects;}
void jt808_set_terminal_profile(const char *m,const char *p){(void)m;(void)p;++effects;}
void jt808_reset_endpoint_auth(uint8_t mask){assert(mask);++effects;}
void jt808_request_reregister(void){++effects;}
void tcp_manager_reconnect(void){assert(acks);++reconnects;}
void tcp_manager_request_reconnect(void){assert(acks);++reconnects;}
void ec800m_restart_pdp(void){++effects;}
uint32_t work_mode_sleep_monotonic_s(void){return 777;}
void work_mode_config_changed(const device_config_t *c,uint32_t s){assert(c==&cfg);(void)s;++effects;}
int dbg_printf(const char *fmt,...){(void)fmt;return 0;}
int jt808_send_general_resp(uint16_t sn,uint16_t id,uint8_t r){(void)sn;(void)id;result=r;++acks;return 0;}
int jt808_send_raw(uint16_t id,uint16_t sn,const uint8_t *p,uint16_t n){assert(id==0x0104);(void)sn;memcpy(response,p,n);response_len=n;return 0;}
uint8_t jt808_encode_plate_gbk(const char *p,uint8_t *out,uint8_t cap){size_t n=strlen(p);assert(n<=cap);memcpy(out,p,n);return (uint8_t)n;}
jt808_terminal_info_result_t jt808_terminal_info_encode(uint8_t *p,uint16_t n,uint16_t *out){(void)p;(void)n;(void)out;return JT808_TERMINAL_INFO_INVALID_ICCID;}
static uint16_t item(uint8_t *p,uint32_t id,uint32_t v,uint8_t n){p[0]=id>>24;p[1]=id>>16;p[2]=id>>8;p[3]=id;p[4]=n;for(unsigned i=0;i<n;++i)p[5+i]=(uint8_t)(v>>(8*(n-1-i)));return 5+n;}
static void reject(const uint8_t *p,uint16_t n){device_config_t before=cfg;unsigned s=saves,e=effects;result=0;jt808_params_handle_set(p,n,9);assert(result!=0);assert(!memcmp(&cfg,&before,sizeof cfg));assert(saves==s&&effects==e);}
int main(void){
    cfg.heartbeat_s=180;cfg.report_moving_s=30;cfg.report_stopped_s=60;
    cfg.server_port=cfg.backup_port=8898;strcpy(cfg.server_ip,"old.example");
    uint8_t bad[]={1,0,0,0,1,4,0};reject(bad,sizeof bad);
    reject(NULL,0);
    uint8_t b[256];uint16_t n=1;b[0]=11;
    n+=item(b+n,1,120,4);
    n+=item(b+n,0x13,0x74657374,4); /* four-byte STRING "test" */
    n+=item(b+n,0x18,9000,4);n+=item(b+n,0x27,60,4);n+=item(b+n,0x29,30,4);
    n+=item(b+n,0x80,12345,4);n+=item(b+n,0x81,44,2);n+=item(b+n,0x82,300,2);
    n+=item(b+n,0x83,0x41313233,4);n+=item(b+n,0x84,2,1);
    n+=item(b+n,0x55,100,4);
    jt808_params_handle_set(b,n,0x1234);assert(result==0&&saves==1);
    assert(cfg.heartbeat_s==120&&cfg.mileage_m==1234500&&cfg.server_port==9000);
    assert(!strcmp(cfg.server_ip,"test")&&!strcmp(cfg.plate_no,"A123"));
    assert(reconnects==1);assert(!memcmp(&cfg,&disk,sizeof cfg));
    jt808_params_handle_set(b,n,0x1234);assert(saves==1&&result==0);
    for(uint16_t i=0;i<n;++i)reject(b,i);
    b[n]=0;reject(b,n+1);
    uint8_t q[]={11,0,0,0,1,0,0,0,0x13,0,0,0,0x18,0,0,0,0x27,0,0,0,0x29,0,0,0,0x80,0,0,0,0x81,0,0,0,0x82,0,0,0,0x83,0,0,0,0x84,0,0,0,0x55};
    jt808_params_handle_query(q,sizeof q,0x1234);
    assert(response_len==n+2&&response[0]==0x12&&response[1]==0x34&&response[2]==11);
    assert(!memcmp(response+3,b+1,n-1));
    /* Reboot/load preserves the exact query representation. */
    memset(&cfg,0,sizeof cfg);cfg=disk;jt808_params_handle_query(q,sizeof q,0x1234);
    assert(!memcmp(response+3,b+1,n-1));
    unsigned s=saves,e=effects;fail_store=true;b[9]=121;
    device_config_t old=cfg;jt808_params_handle_set(b,n,9);
    assert(result==1&&saves==s+1&&effects==e&&!memcmp(&old,&cfg,sizeof cfg));fail_store=false;
    b[0]=1;n=1+item(b+1,0x80,0xffffffff,4);reject(b,n);
    n=1+item(b+1,0x18,65536,4);reject(b,n);
    n=1+item(b+1,0x29,0,4);reject(b,n);
    n=1+item(b+1,0x29,4,4);reject(b,n);
    n=1+item(b+1,1,120,2);reject(b,n);
    n=1+item(b+1,0x84,255,1);reject(b,n);
    n=1+item(b+1,0xffff,0,4);reject(b,n);
    b[0]=2;n=1+item(b+1,1,120,4);n+=item(b+n,1,121,4);reject(b,n);
    b[0]=1;n=1+item(b+1,0x13,0x61006263,4);reject(b,n);
    assert(service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_OTA));
    n=1+item(b+1,1,120,4);reject(b,n);service_workspace_release(SERVICE_WORKSPACE_OWNER_OTA);
    response_len=0;jt808_params_handle_query(q,sizeof q-1,9);assert(response_len==0&&result!=0);
    assert(cfg.speed_limit_kmh==100);
    for(unsigned v=20;v<=200;v+=180){b[0]=1;n=1+item(b+1,0x55,v,4);jt808_params_handle_set(b,n,9);assert(result==0&&cfg.speed_limit_kmh==v);}
    n=1+item(b+1,0x55,19,4);reject(b,n);
    n=1+item(b+1,0x55,201,4);reject(b,n);
    n=1+item(b+1,0x55,0x10064,4);reject(b,n);
    n=1+item(b+1,0x55,100,2);reject(b,n);
    /* Exact field values from the user's location-report packet. */
    b[0]=4;n=1+item(b+1,0x29,30,4);n+=item(b+n,0x27,180,4);
    n+=item(b+n,0x20,0,4);n+=item(b+n,0x21,0,4);
    jt808_params_handle_set(b,n,0x6a);assert(result==0&&cfg.report_stopped_s==180);
    uint8_t modes[]={4,0,0,0,0x29,0,0,0,0x27,0,0,0,0x20,0,0,0,0x21};
    jt808_params_handle_query(modes,sizeof modes,0x6a);assert(response_len==n+2&&!memcmp(response+3,b+1,n-1));
    s=saves;jt808_params_handle_set(b,n,0x6a);assert(result==0&&saves==s);
    b[n-1]=1;reject(b,n);assert(result==3);b[n-1]=0;b[n-10]=1;reject(b,n);assert(result==3);
    b[0]=1;n=1+item(b+1,0x20,0,2);reject(b,n);assert(result==2);
    return 0;
}
'''
def main():
    with tempfile.TemporaryDirectory() as d:
        p=Path(d);(p/'n32l40x.h').write_text('#pragma once\n')
        (p/'h.c').write_text(HARNESS)
        cmd=[os.environ.get('CC') or shutil.which('gcc'),'-std=c99','-Wall','-Wextra','-Werror','-I',str(p),'-I',str(ROOT/'include'),str(p/'h.c'),str(ROOT/'src/jt808_params.c'),str(ROOT/'src/service_workspace.c'),'-o',str(p/'h.exe')]
        subprocess.run(cmd,check=True);subprocess.run([str(p/'h.exe')],check=True)
    print('test_jt808_params: PASS')
if __name__=='__main__':main()
