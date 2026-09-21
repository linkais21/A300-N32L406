"""Real filter + JT808 wire regression; --baseline demonstrates pre-port drift."""
from pathlib import Path
import subprocess
import sys
import tempfile
import test_jt808_dual_session as dual

ROOT = Path(__file__).resolve().parents[2]
MAIN = r'''
#include "gps_report_filter.h"
#include "i2c_accel.h"
#include "fota.h"
#include "at_config.h"
/* Dependencies added since the shared transport fixture was written. */
static fota_state_t fota_state = FOTA_STATE_IDLE;
fota_state_t fota_get_state(void) { return fota_state; }
void ec800m_tcp_close(uint8_t ch) { open_ch[ch]=false; }
void gps_get_unfixed_report(gps_data_t *out) { memset(out,0,sizeof(*out)); }
bool at_config_execute_text_response(const uint8_t *text, uint16_t len,
    at_config_text_ack_fn ack, at_config_text_reply_fn reply, void *context) {
 (void)text; (void)len; (void)ack; (void)reply; (void)context;
 assert(!"text command outside location fixture"); return false;
}
bool gps_is_enabled(void) { return true; }
bool gps_is_valid(void) { return gps.valid; }
bool gps_quality_fix_fresh(void) { return gps.valid; }
bool i2c_accel_read(accel_data_t *a) { a->x=0; a->y=0; a->z=1024; return true; }
static uint32_t u32(const uint8_t *p) {
 return ((uint32_t)p[0]<<24)|((uint32_t)p[1]<<16)|((uint32_t)p[2]<<8)|p[3];
}
int main(void) {
 (void)test_rx_overlap;
 jt808_terminal_t t={0}; uint8_t d[1024]; uint16_t sn0,sn3,n;
 strcpy(cfg.pid,"56789012345"); cfg.heartbeat_s=600; cfg.stopdrift_en=1;
 strcpy(t.terminal_model,"A300_406"); memcpy(t.manufacturer_id,"70110",5);
 open_ch[0]=open_ch[3]=true; generation[0]=generation[3]=1;
 jt808_init(&t); jt808_process();
 msg(0,&sn0,d,&n); msg(3,&sn3,d,&n);
 reg_resp(0,sn0,"TEST"); jt808_process(); msg(0,&sn0,d,&n);
 reg_resp(3,sn3,"TEST"); jt808_process(); msg(3,&sn3,d,&n);
 auth_resp(0,sn0,0); auth_resp(3,sn3,0);
 gps.valid=true; gps.fix_quality=1; gps.lat=50; gps.lon=10;
 gps.year=2026; gps.month=9; gps.day=17; gps.speed_kmh=0.3f;
 gps.hdop=0.9f; gps.satellites=9;
 gps_report_filter_init();
 for(unsigned i=0;i<180;i++) {
   g_tick_ms+=200; gps.last_update_ms=g_tick_ms;
   if(i%5==0) gps.heading_update_ms=g_tick_ms;
   gps_report_filter_process(g_tick_ms);
 }
 /* Sleep sends a fresh first fix once per channel and retries only failures. */
 work_state=WORK_MODE_STATIONARY_SLEEP; fail_send[3]=true;
 unsigned sleep0=sends[0], sleep3=sends[3];
 jt808_process();assert(sends[0]==sleep0+1 && sends[3]==sleep3+1);
 assert(msg(0,&sn0,d,&n)==0x0200);
 fail_send[3]=false;
 jt808_process();assert(sends[0]==sleep0+1 && sends[3]==sleep3+2);
 assert(msg(3,&sn0,d,&n)==0x0200);
 jt808_process();assert(sends[0]==sleep0+1 && sends[3]==sleep3+2);
 gps.valid=false;jt808_process();
 assert(sends[0]==sleep0+1 && sends[3]==sleep3+2);
 gps.valid=true;work_state=WORK_MODE_REALTIME;
 gps.lat=50.002; /* stationary GNSS wanders >100m after anchor */
 gps.last_update_ms=gps.heading_update_ms=g_tick_ms;
 gps_report_filter_process(g_tick_ms);
 assert(jt808_send_location()==0);
 for(unsigned ch=0;ch<=3;ch+=3) {
   assert(msg(ch,&sn0,d,&n)==0x0200);
   assert(u32(d+20)==50000000 && u32(d+24)==10000000);
   assert(d[30]==0 && d[31]==0);
 }
 assert(gps.lat==50.002 && gps.speed_kmh==0.3f);
 /* Weak stationary speed must be filtered on the actual 0200 wire too. */
 gps.hdop=4.0f; gps.satellites=9; gps.speed_kmh=2.5f;
 for(unsigned i=0;i<20;i++) {
   g_tick_ms+=200; gps.last_update_ms=g_tick_ms;
   if(i%5==0) gps.heading_update_ms=g_tick_ms;
   gps_report_filter_process(g_tick_ms);
 }
 assert(jt808_send_location()==0);
 for(unsigned ch=0;ch<=3;ch+=3) {
   assert(msg(ch,&sn0,d,&n)==0x0200);
   assert(u32(d+20)==50000000 && u32(d+24)==10000000);
   assert(d[30]==0 && d[31]==0 && (d[19]&2));
 }
 assert(jt808_send_location_work_mode(0,false,1U)==0);
 msg(0,&sn0,d,&n); assert(u32(d+20)==50000000);
 query(0,0x8201); assert(msg(0,&sn0,d,&n)==0x0201);
 assert(u32(d+20)==50000000);
 /* Confirmed smooth movement reports now, even with a long periodic interval. */
 gps.lat=50; gps.lon=10; gps.heading=0; gps.speed_kmh=1.0f;
 jt808_process(); /* finish any pending first-fix scheduling */
 unsigned before=sends[0];
 for(unsigned i=0;i<150;i++) {
   g_tick_ms+=200; gps.lat+=(1.0/3.6)*0.2/111319.5;
   gps.last_update_ms=g_tick_ms;
   if(i%5==0) gps.heading_update_ms=g_tick_ms;
   gps_report_filter_process(g_tick_ms); jt808_process();
 }
 assert(sends[0]==before+1);
 assert(msg(0,&sn0,d,&n)==0x0200);
 assert(u32(d+20)>50000000 && d[31]==10);
 before=sends[0];jt808_process();assert(sends[0]==before);
 /* Historical retained positions are never filtered a second time. */
 trusted_available=true;
 assert(jt808_send_location_work_mode(0,true,1U)==0);
 msg(0,&sn0,d,&n); assert(u32(d+20)==(uint32_t)(gps.lat*1000000.0));
 gps_report_filter_reset();
 assert(jt808_send_location_to(0,&gps)==0);
 msg(0,&sn0,d,&n); assert(u32(d+20)==(uint32_t)(gps.lat*1000000.0));
 /* A new event retries live delivery without creating blind-zone records. */
 gps.speed_kmh=0.3f; gps.hdop=0.9f;
 for(unsigned i=0;i<180;i++) {
   g_tick_ms+=200; gps.last_update_ms=g_tick_ms;
   if(i%5==0) gps.heading_update_ms=g_tick_ms;
   gps_report_filter_process(g_tick_ms); jt808_process();
 }
 gps.speed_kmh=2.0f;
 for(unsigned i=0;i<3;i++) {
   g_tick_ms+=200; gps.last_update_ms=gps.heading_update_ms=g_tick_ms;
   gps_report_filter_process(g_tick_ms);
 }
 assert(gps_report_filter_motion_pending(g_tick_ms));
 before=sends[0];
 fota_state=FOTA_STATE_DOWNLOADING;jt808_process();assert(sends[0]==before);
 fota_state=FOTA_STATE_IDLE;
 work_state=WORK_MODE_STATIONARY_SLEEP;jt808_process();assert(sends[0]==before);
 work_state=WORK_MODE_REALTIME;
 gps.valid=false;jt808_process();assert(sends[0]==before);
 gps.valid=true;
 fail_send[0]=fail_send[3]=true;
 unsigned appends_before=append_calls;
 before=sends[0]; jt808_process();
 assert(sends[0]==before+1 && append_calls==appends_before);
 assert(gps_report_filter_motion_pending(g_tick_ms));
 for(unsigned i=0;i<4;i++) {
   g_tick_ms+=200;gps.last_update_ms=gps.heading_update_ms=g_tick_ms;
   gps_report_filter_process(g_tick_ms);jt808_process();
 }
 assert(sends[0]==before+1);
 fail_send[0]=false;
 g_tick_ms+=200;gps.last_update_ms=gps.heading_update_ms=g_tick_ms;
 gps_report_filter_process(g_tick_ms);jt808_process();
 assert(sends[0]==before+2 && !gps_report_filter_motion_pending(g_tick_ms));
 assert(append_calls==appends_before);
 /* Ordinary live broadcasts accept either channel; alarms require both.
  * All-channel failure stores one record and releases the frame workspace. */
 append_result=BLIND_ZONE_OK;
 for(unsigned mask=0;mask<4;mask++) {
   fail_send[0]=(mask&1)!=0;fail_send[3]=(mask&2)!=0;
   before=sends[0];unsigned back_before=sends[3];appends_before=append_calls;
   assert(jt808_send_location()==0);
   assert(sends[0]==before+1 && sends[3]==back_before+1);
   assert(append_calls==appends_before+(mask==3));
 }
 fail_send[0]=false;fail_send[3]=true;appends_before=append_calls;
 assert(jt808_send_location_work_mode(1U,false,99U)==0);
 assert(append_calls==appends_before+1);
 fail_send[3]=false;before=sends[0];
 assert(jt808_send_location()==0 && sends[0]==before+1);
 /* Exercise the real corner state machine and its cached-point broadcast. */
 gps_report_filter_reset();gps.speed_kmh=40.0f;
 cfg.anglerep_angle=30;cfg.anglerep_speed=5;
 for(unsigned mask=0;mask<4;mask++) {
   cfg.anglerep_en=0;jt808_process();
   cfg.anglerep_en=1;
   fail_send[0]=(mask&1)!=0;fail_send[3]=(mask&2)!=0;
   before=sends[0];unsigned back_before=sends[3];appends_before=append_calls;
   for(unsigned i=0;i<4;i++) {
     g_tick_ms+=1000;gps.last_update_ms=gps.heading_update_ms=g_tick_ms;
     gps.heading=i*15.0f;jt808_process();
   }
   assert(sends[0]==before+2 && sends[3]==back_before+2);
   assert(append_calls==appends_before+(mask==3?2:0));
 }
 return 0;
}
'''
source = dual.HARNESS.split('int main(void) {')[0]
source = source.replace('bool gps_report_filter_copy(const gps_data_t *raw, gps_data_t *out, uint32_t now) { (void)now; *out=*raw; return false; }', '')
source = source.replace('bool gps_get_last_trusted(gps_data_t *out) { (void)out; return false; }',
                        'bool gps_get_last_trusted(gps_data_t *out) { *out=gps; return true; }')
with tempfile.TemporaryDirectory() as tmp:
    d = Path(tmp)
    (d/'h.c').write_text(source + MAIN, encoding='ascii')
    (d/'n32l40x.h').write_text('#pragma once\n#define GPIOA ((void*)0)\n#define GPIO_PIN_12 12U\n#define Bit_RESET 0\nint GPIO_ReadInputDataBit(void*,unsigned);\n')
    jt = ROOT / ('build-detail-optimization/baseline/src/jt808.c' if '--baseline' in sys.argv else 'src/jt808.c')
    subprocess.run([dual.compiler(), '-std=c99', '-Wall', '-Wextra', '-Werror',
                    '-I', str(d), '-I', str(ROOT/'include'), str(d/'h.c'), str(jt),
                    *[str(ROOT/'src'/f) for f in ('plate_encoding.c','gps_report_filter.c','jt808_session.c','terminal_identity.c','motion_corner.c')],
                    '-lm', '-o', str(d/'h.exe')], check=True)
    subprocess.run([str(d/'h.exe')], check=True)
print('GPS filter -> JT808 main/backup/query/work-mode, history untouched: PASS')
