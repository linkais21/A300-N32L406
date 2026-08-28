#!/usr/bin/env python3
import os, pathlib, subprocess, tempfile, shutil, sys
ROOT = pathlib.Path(__file__).resolve().parents[2]
HARNESS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <math.h>
#include <string.h>
#include "f39_reply.h"
#include "f39_command.h"
#include "flash_config.h"
typedef struct { unsigned saves, reconnects, timers, gnss, relays, resets; bool persist_ok, gps_ok; float speed; bool relay; gnss_type_t receiver; uint8_t mode; char order[8]; unsigned order_len; f39_reply_t *reply; } spy_t;
static void mark(spy_t*s,char c){s->order[s->order_len++]=c;s->order[s->order_len]='\0';}
static bool save(const device_config_t *c, void *p){ (void)c; spy_t*s=p; s->saves++; return s->persist_ok; }
static void reconnect(void*p){spy_t*s=p;s->reconnects++;mark(s,'N');}
static void timers(void*p){spy_t*s=p;s->timers++;mark(s,'T');}
static void register808(void*p){mark((spy_t*)p,'J');}
static void remaining(void*p){mark((spy_t*)p,'R');}
static void gnss(gnss_type_t r,uint8_t m,void*p){spy_t*s=p;assert(r==GNSS_TYPE_TAU804M||r==GNSS_TYPE_ATGM332D_F7N);assert(m>=1&&m<=3);s->gnss++;s->receiver=r;s->mode=m;mark(s,'G');}
static bool relay(bool on,void*p){spy_t*s=p;s->relays++;s->relay=on;return true;}
static bool relay_get(void*p){return ((spy_t*)p)->relay;}
static bool gps(void*p){return ((spy_t*)p)->gps_ok;}
static float speed(void*p){return ((spy_t*)p)->speed;}
static f39_platform_t platform(device_config_t*c,spy_t*s){f39_platform_t p;memset(&p,0,sizeof(p));p.config=c;p.persist=save;p.context=s;p.network_reconnect=reconnect;p.timer_refresh=timers;p.gnss_set_mode=gnss;p.jt808_reregister=register808;p.remaining_refresh=remaining;p.relay_set=relay;p.relay_get=relay_get;p.gps_valid=gps;p.gps_speed_kmh=speed;p.version="V3";p.version_len=2;p.imei="123456789012345";p.imei_len=15;p.csq=25;p.acc_on=true;p.gps_fix_quality=1;p.gps_satellites=9;return p;}
static f39_result_t run(const char*t, device_config_t*c, spy_t*s, f39_reply_t*r){f39_request_t q;f39_platform_t p=platform(c,s);s->reply=r;assert(f39_parse((const uint8_t*)t,(uint16_t)strlen(t),&q)==F39_RESULT_OK);return f39_execute(&q,&p,r);}
static device_config_t seed(void){device_config_t c;memset(&c,0,sizeof(c));c.gnss_type=GNSS_TYPE_TAU804M;strcpy(c.server_ip,"host");c.server_port=9000;strcpy(c.backup_ip,"backup");c.backup_port=9001;c.heartbeat_s=60;c.report_moving_s=30;c.report_stopped_s=300;c.gpsbds_mode=2;c.speed_limit_kmh=80;c.gmt_sign=1;c.gmt_hour=8;strcpy(c.pid,"12345678901");strcpy(c.terminal_model,"A300");strcpy(c.apn,"cmnet");strcpy(c.apn_user,"USERSECRET");strcpy(c.apn_pass,"PASSSECRET");strcpy(c.auth_code,"AUTHSECRET");strcpy(c.agnss_user,"AGNSSUSER");strcpy(c.agnss_pwd,"AGNSSPASS");return c;}
int main(void){static const char*queries[]={"PID","IP","FIP","FREQ","HBT","MODEL","SPEED","APN","RELAY","GPSDUP","MLG","CAR","GPSBDS","GMTSET"};device_config_t c=seed(),before;spy_t s={0};f39_reply_t r;size_t i;s.persist_ok=true;
 assert(run("PARAM",&c,&s,&r)==F39_RESULT_OK);assert(r.len>0&&r.len<F39_REPLY_MAX_LENGTH);assert(strstr((char*)r.data,"PASSSECRET")==0);assert(strstr((char*)r.data,"USERSECRET")==0);assert(strstr((char*)r.data,"AUTHSECRET")==0);assert(strstr((char*)r.data,"AGNSSPASS")==0);assert(strstr((char*)r.data,"Success!")!=0);assert(strstr((char*)r.data,",SV=")!=0);
 for(i=0;i<sizeof(queries)/sizeof(queries[0]);i++){assert(run(queries[i],&c,&s,&r)==F39_RESULT_OK);assert(r.len>0&&r.len<F39_REPLY_MAX_LENGTH);}
 assert(run("GPSBDS,1",&c,&s,&r)==F39_RESULT_OK);assert(s.gnss==1&&s.receiver==GNSS_TYPE_TAU804M&&s.mode==1);
 c.gnss_type=GNSS_TYPE_ATGM332D_F7N;assert(run("GPSBDS,3",&c,&s,&r)==F39_RESULT_OK);assert(s.receiver==GNSS_TYPE_ATGM332D_F7N&&s.mode==3);
 c.gnss_type=GNSS_TYPE_UNKNOWN;before=c;{unsigned saves=s.saves;assert(run("GPSBDS,2",&c,&s,&r)!=F39_RESULT_OK);assert(s.saves==saves&&memcmp(&c,&before,sizeof(c))==0);}
 c.gnss_type=GNSS_TYPE_TAU804M;s.gps_ok=false;s.speed=0;assert(run("RELAY,1",&c,&s,&r)!=F39_RESULT_OK);assert(s.relays==0);
 s.gps_ok=true;s.speed=20.0f;assert(run("RELAY,1",&c,&s,&r)!=F39_RESULT_OK);assert(s.relays==0);
 s.speed=19.999f;assert(run("RELAY,1",&c,&s,&r)==F39_RESULT_OK);assert(s.relay&&s.relays==1);assert(run("RELAY",&c,&s,&r)==F39_RESULT_OK);assert(strstr((char*)r.data,"RELAY,1")!=0);
 s.speed=NAN;assert(run("RELAY,1",&c,&s,&r)!=F39_RESULT_OK);assert(s.relays==1);
 s.gps_ok=false;s.speed=100;assert(run("RELAY,0",&c,&s,&r)==F39_RESULT_OK);assert(!s.relay&&s.relays==2);
 s.order_len=0;assert(run("DUALSET,FREQ,5,60*IP,new,8000*GPSBDS,3*MODEL,T360",&c,&s,&r)==F39_RESULT_OK);assert(strcmp(s.order,"TNGJR")==0);
 before=c;s.persist_ok=false;{unsigned saves=s.saves;unsigned gnss_calls=s.gnss;assert(run("GPSBDS,1",&c,&s,&r)!=F39_RESULT_OK);assert(s.saves==saves+1&&s.gnss==gnss_calls&&memcmp(&c,&before,sizeof(c))==0);}s.persist_ok=true;
 {static const char*cmds[]={"FREQ,5,60","IP,x,1","GPSBDS,1","MODEL,X","MODEL,X"};unsigned i;for(i=0;i<5;i++){f39_request_t q;device_config_t x=seed();spy_t z={0};f39_reply_t rr;f39_platform_t p=platform(&x,&z);z.persist_ok=true;if(i==0)p.timer_refresh=0;if(i==1)p.network_reconnect=0;if(i==2)p.gnss_set_mode=0;if(i==3)p.jt808_reregister=0;if(i==4)p.remaining_refresh=0;assert(f39_parse((const uint8_t*)cmds[i],(uint16_t)strlen(cmds[i]),&q)==F39_RESULT_OK);assert(f39_execute(&q,&p,&rr)!=F39_RESULT_OK);assert(z.saves==0);} }
 s.resets=0;assert(run("RESET",&c,&s,&r)==F39_RESULT_OK);assert(s.resets==0);assert(r.reset_pending&&r.reset_delay_ms==F39_RESET_DELAY_MS);assert(strstr((char*)r.data,"Success!")!=0);
 { device_config_t empty=seed(); spy_t z={0}; f39_reply_t rr; empty.pid[0]='\0'; assert(run("PID",&empty,&z,&rr)==F39_RESULT_OK); assert(strstr((char*)rr.data,"PID,56789012345")!=0); }
 { device_config_t bad=seed(); spy_t z={0}; f39_reply_t rr; memset(bad.terminal_model,'X',sizeof(bad.terminal_model)); assert(run("MODEL",&bad,&z,&rr)!=F39_RESULT_OK); }
 { device_config_t q=seed(); spy_t z={0}; f39_reply_t rr; assert(run("IP,new,8000",&q,&z,&rr)!=F39_RESULT_OK); }
 {f39_request_t q;f39_platform_t p=platform(&c,&s);static char huge[300];memset(huge,'V',sizeof(huge));assert(f39_parse((const uint8_t*)"PARAM",5,&q)==F39_RESULT_OK);p.version=huge;p.version_len=sizeof(huge);assert(f39_execute(&q,&p,&r)!=F39_RESULT_OK);assert(r.len<F39_REPLY_MAX_LENGTH);}
 return 0; }
'''
def find_compiler():
    compiler = shutil.which('gcc') or shutil.which('cc')
    if compiler:
        return compiler
    base = pathlib.Path(os.environ.get('LOCALAPPDATA', '')) / 'Microsoft' / 'WinGet' / 'Packages'
    matches = list(base.glob('BrechtSanders.WinLibs*/mingw64/bin/gcc.exe'))
    return str(matches[0]) if matches else None
def main():
 cc=find_compiler()
 if not cc: print('test_f39_actions: SKIP'); return 0
 with tempfile.TemporaryDirectory() as d:
  h=pathlib.Path(d)/'h.c'; b=pathlib.Path(d)/'h'; h.write_text(HARNESS)
  cmd=[cc,'-std=c99','-Wall','-Wextra','-Werror','-I',str(ROOT/'include'),str(h),str(ROOT/'src/f39_command.c'),str(ROOT/'src/f39_config_adapter.c'),str(ROOT/'src/f39_reply.c'),'-o',str(b)]
  x=subprocess.run(cmd,cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT); print(x.stdout,end='');
  if x.returncode:return x.returncode
  x=subprocess.run([str(b)],text=True)
  if x.returncode==0: print('test_f39_actions: PASS')
  return x.returncode
if __name__=='__main__': sys.exit(main())
