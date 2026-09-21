"""Real log formatter / UDP handoff using synthetic SIM identity only."""
from pathlib import Path
import shutil, subprocess, tempfile
ROOT=Path(__file__).resolve().parents[2]
HARNESS=r'''
#include <assert.h>
#include <string.h>
#include "log_platform.c"
volatile uint32_t g_tick_ms;
static device_config_t cfg;
static const char *iccid="89860000000000000001";
static uint8_t workspace[1024];
static size_t capacity=sizeof workspace;
static unsigned sends, releases;
static bool online=true, locked;
device_config_t *cfg_get(void){return &cfg;}
void ec800m_get_imei(char *b,uint8_t n){snprintf(b,n,"123456789012345");}
void ec800m_get_iccid(char *b,uint8_t n){snprintf(b,n,"%s",iccid);}
int ec800m_get_csq(void){return 20;}
bool gps_is_valid(void){return true;}
bool jt808_is_online(void){return online;}
bool work_mode_sleep_is_in_stop1(void){return false;}
fota_state_t fota_get_state(void){return FOTA_STATE_IDLE;}
bool service_workspace_try_acquire(service_workspace_owner_t o){(void)o;if(locked)return false;locked=true;return true;}
void service_workspace_release(service_workspace_owner_t o){(void)o;locked=false;++releases;}
uint8_t *service_workspace_buffer(size_t *n){*n=capacity;return workspace;}
int ec800m_udp_send_once(const char *ip,uint16_t port,const uint8_t *data,uint16_t len){
 (void)ip;(void)port;assert(locked);assert(len<capacity);assert(data[len-1]=='>');++sends;return 0;
}
int main(void){
 uint8_t b[1024]; unsigned n=build_log(b,sizeof b);
 assert(n>0 && n<sizeof b);
 assert(strstr((char*)b,"*6F:0,89860000000000000001,,*")!=NULL);
 iccid="";n=build_log(b,sizeof b);assert(n>0);
 assert(strstr((char*)b,"*6F:1,,,*")!=NULL);
 iccid="bad*ID";n=build_log(b,sizeof b);assert(n>0);
 assert(strstr((char*)b,"*6F:1,,,*")!=NULL);
 assert(build_log(b,64)==0); /* never send snprintf's would-have-written length */
 iccid="89860000000000000001";
 log_platform_init();log_platform_on_first_online();log_platform_process();assert(sends==1 && releases==1);
 log_platform_process();assert(sends==1);
 capacity=64;log_platform_on_first_online();log_platform_process();assert(sends==1 && releases==2);
 capacity=sizeof workspace;log_platform_process();assert(sends==2);
 online=false;log_platform_on_first_online();log_platform_process();assert(sends==2);
 puts("log platform 6F / ICCID / truncation / handoff: PASS");return 0;
}
'''
with tempfile.TemporaryDirectory() as d:
    d=Path(d);(d/'n32l40x.h').write_text('#include <stdint.h>\n',encoding='ascii')
    (d/'h.c').write_text(HARNESS,encoding='ascii')
    cc=shutil.which('gcc');assert cc
    subprocess.run([cc,'-std=c99','-Wall','-Wextra','-Werror','-I',str(d),'-I',str(ROOT/'include'),'-I',str(ROOT/'src'),str(d/'h.c'),'-o',str(d/'h.exe')],check=True)
    subprocess.run([str(d/'h.exe')],check=True)
