"""Real log formatter / UDP handoff using synthetic SIM identity only."""
from pathlib import Path
import shutil, subprocess, tempfile
ROOT=Path(__file__).resolve().parents[2]
HARNESS=r'''
#include <assert.h>
#include <string.h>
#include "n32l40x_rtc.h"
#include "log_platform.c"
volatile uint32_t g_tick_ms;
static device_config_t cfg;
static const char *iccid="89860000000000000001";
static uint8_t workspace[1024];
static size_t capacity=sizeof workspace;
static unsigned sends, releases;
static bool online=true, locked;
static bool sim_ready=true, adc_valid=true;
static float voltage=12.36f;
bool ec800m_sim_ready(void){return sim_ready;}
bool adc_monitor_valid(void){return adc_valid;}
float adc_get_car_voltage(void){return voltage;}
void RTC_GetTime(uint32_t format, RTC_TimeType *t){(void)format;t->Hours=9;t->Minutes=8;t->Seconds=7;}
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
 assert(strstr((char*)b,"*R:090807*")!=NULL);
 assert(strstr((char*)b,"*4C:124*")!=NULL);
 sim_ready=false;build_log(b,sizeof b);assert(strstr((char*)b,"*6F:1,89860000000000000001,,*")!=NULL);
 sim_ready=true;adc_valid=false;build_log(b,sizeof b);assert(strstr((char*)b,"*4C:0*")!=NULL);
 adc_valid=true;voltage=-1;build_log(b,sizeof b);assert(strstr((char*)b,"*4C:0*")!=NULL);
 voltage=12.36f;build_log(b,sizeof b);
 assert(strstr((char*)b,"*6F:0,89860000000000000001,,*")!=NULL);
 iccid="898600A0000000000001";n=build_log(b,sizeof b);assert(n>0);
 assert(strstr((char*)b,"*6F:0,898600A0000000000001,,*")!=NULL);
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
    (d/'n32l40x_rtc.h').write_text('#pragma once\n#include <stdint.h>\ntypedef struct {uint8_t Hours,Minutes,Seconds;} RTC_TimeType;\n#define RTC_FORMAT_BIN 0\nvoid RTC_GetTime(uint32_t,RTC_TimeType *);\n',encoding='ascii')
    (d/'h.c').write_text(HARNESS,encoding='ascii')
    cc=shutil.which('gcc');assert cc
    subprocess.run([cc,'-std=c99','-Wall','-Wextra','-Werror','-I',str(d),'-I',str(ROOT/'include'),'-I',str(ROOT/'src'),str(d/'h.c'),'-o',str(d/'h.exe')],check=True)
    subprocess.run([str(d/'h.exe')],check=True)
