"""Actual JT808 RX -> params -> encoded ACK/query/registration on both channels."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import re

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('dual',Path(__file__).with_name('test_jt808_dual_session.py'))
dual=importlib.util.module_from_spec(spec);spec.loader.exec_module(dual)

def main():
    baseline='--baseline-warning' in sys.argv
    def production_source(name):
        if baseline:
            return subprocess.check_output(['git','show','HEAD:src/'+name],cwd=ROOT).decode('utf-8')
        return (ROOT/'src'/name).read_text(encoding='utf-8')
    source=dual.HARNESS
    start=source.index('void jt808_params_handle_set(')
    end=source.index('jt808_terminal_info_result_t jt808_terminal_info_encode(',start)
    source=source[:start]+source[end:]
    source=source.replace('int main(void)', 'int original_main(void)')
    source=source.replace('(void)p; (void)pin; return 0;', '(void)p; return pin==2U ? 1 : 0;')
    source+=r'''
static unsigned reconnect_requests;
void tcp_manager_request_reconnect(void) { ++reconnect_requests; }
void tcp_manager_reconnect_channels(uint8_t mask) { assert(mask==1U || mask==8U || mask==9U); ++reconnect_requests; }
void ec800m_restart_pdp(void) { }
uint32_t work_mode_sleep_monotonic_s(void) { return g_tick_ms/1000U; }
void work_mode_config_changed(const device_config_t *c,uint32_t now) { (void)c;(void)now; }
static uint32_t scanned_alarms;
static unsigned warning_events;
void work_mode_notify_alarm(uint32_t bits) {
    scanned_alarms |= bits;
    if (bits & ALM_OVERSPEED_WARNING) ++warning_events;
}
bool adc_is_car_powered(void) { return true; }
bool adc_is_bat_low(void) { return false; }
#include "overspeed_policy.h"
#include "config.h"
static overspeed_policy_t s_overspeed_policy;
'''
    # Exercise the production scanner, with only hardware inputs stubbed.
    main_source=production_source('main.c')
    start=main_source.index('static void scan_alarms(void)')
    end=main_source.index('\n}\n',start)+3
    source+=main_source[start:end]
    source+=r'''
int main(void) {
    jt808_terminal_t terminal={0};uint8_t decoded[1024];uint16_t sn,len;
    strcpy(terminal.manufacturer_id,"70110");strcpy(terminal.terminal_model,"T360-A300");terminal.color=1;
    memset(&cfg,0,sizeof cfg);strcpy(cfg.pid,"56789012345");cfg.server_port=8898;
    cfg.heartbeat_s=180;cfg.report_moving_s=30;cfg.report_stopped_s=60;
    open_ch[0]=open_ch[3]=true;
    for (unsigned ch=0;ch<=3;ch+=3) {
        gps.valid=false;
        strcpy(cfg.auth_code,"AUTH");strcpy(cfg.backup_auth_code,"AUTH");
        jt808_init(&terminal);jt808_set_terminal_profile(NULL,cfg.plate_no);jt808_process();
        for(unsigned x=0;x<=3;x+=3){assert(msg(x,&sn,decoded,&len)==0x0102);auth_resp(x,sn,0);}
        /* User's 37-byte body, with the terminal identity supplied by the
         * synthetic harness rather than retaining a real device identifier. */
        const uint8_t location[]={4,0,0,0,0x29,4,0,0,0,30,
            0,0,0,0x27,4,0,0,0,180,0,0,0,0x20,4,0,0,0,0,
            0,0,0,0x21,4,0,0,0,0};
        inject(ch,0x8103,location,sizeof location);
        assert(msg(ch,&sn,decoded,&len)==1&&decoded[16]==0);
        assert(cfg.report_moving_s==30&&cfg.report_stopped_s==180);
        const uint8_t location_query[]={4,0,0,0,0x29,0,0,0,0x27,0,0,0,0x20,0,0,0,0x21};
        inject(ch,0x8106,location_query,sizeof location_query);
        assert(msg(ch,&sn,decoded,&len)==0x0104&&decoded[14]==4);
        assert(!memcmp(decoded+15,location+1,sizeof location-1));
        /* All requested IDs may arrive together on either authenticated channel. */
        const uint8_t compatibility[]={11,
            0,0,0,0x56,4,0,0,0,3,
            0,0,0,2,4,0,0,0,10,0,0,0,3,4,0,0,0,3,
            0,0,0,4,4,0,0,0,10,0,0,0,0x22,4,0,0,0,60,
            0,0,0,0x28,4,0,0,0,60,0,0,0,0x2c,4,0,0,0,100,
            0,0,0,0x2e,4,0,0,0,100,0,0,0,0x2f,4,0,0,0,100,
            0,0,0,0x30,4,0,0,0,30,0,0,0,0x31,4,0,0,0,100};
        unsigned inactive_other=ch==0?3:0, inactive_sends=sends[inactive_other];
        inject(ch,0x8103,compatibility,sizeof compatibility);
        assert(msg(ch,&sn,decoded,&len)==1&&decoded[16]==0);
        assert(sends[inactive_other]==inactive_sends&&cfg_speed_limit_time_s(&cfg)==3U);
        const uint8_t duration_query[]={1,0,0,0,0x56};
        inject(ch,0x8106,duration_query,sizeof duration_query);
        assert(msg(ch,&sn,decoded,&len)==0x0104&&decoded[14]==1);
        assert(!memcmp(decoded+15,compatibility+1,9));
        const uint8_t speed[]={1,0,0,0,0x55,4,0,0,0,100};
        inject(ch,0x8103,speed,sizeof speed);
        assert(msg(ch,&sn,decoded,&len)==1&&decoded[16]==0&&cfg.speed_limit_kmh==100);
        const uint8_t set[]={5,0,0,0,1,4,0,0,0,120,0,0,0,0x81,2,0,44,
            0,0,0,0x82,2,1,44,0,0,0,0x84,1,2,0,0,0,0x83,8,0xd4,0xc1,'B','1','2','3','4','5'};
        unsigned other=ch==0?3:0, old_sends=sends[other];
        inject(ch,0x8103,set,sizeof set);
        assert(msg(ch,&sn,decoded,&len)==1&&decoded[16]==0);
        assert(sends[other]==old_sends&&cfg.heartbeat_s==120);
        strcpy(cfg.auth_code,"AUTH");strcpy(cfg.backup_auth_code,"AUTH");
        jt808_init(&terminal);jt808_set_terminal_profile(NULL,cfg.plate_no);jt808_process();
        for(unsigned x=0;x<=3;x+=3){assert(msg(x,&sn,decoded,&len)==0x0102);auth_resp(x,sn,0);}
        const uint8_t q[]={2,0,0,0,1,0,0,0,0x83};
        inject(ch,0x8106,q,sizeof q);
        assert(msg(ch,&sn,decoded,&len)==0x0104);
        assert(decoded[12]==0x12&&decoded[13]==0x34&&decoded[14]==2);
        assert(!memcmp(decoded+20,(uint8_t[]){0,0,0,120},4));
        assert(!memcmp(decoded+29,set+sizeof(set)-8,8));
        inject(ch,0x8104,NULL,0);assert(msg(ch,&sn,decoded,&len)==0x0104);
        /* 0x0030 corner angle is now a stored, queryable parameter. */
        assert(decoded[14]==21);
        /* Set on each connection; query uses WORD bytes and the same serial. */
        const uint8_t warning_set[]={1,0,0,0,0x5b,2,0,100};
        inject(ch,0x8103,warning_set,sizeof warning_set);
        assert(msg(ch,&sn,decoded,&len)==1&&decoded[16]==0);
        const uint8_t warning_query[]={1,0,0,0,0x5b};
        inject(ch,0x8106,warning_query,sizeof warning_query);
        assert(msg(ch,&sn,decoded,&len)==0x0104&&decoded[14]==1);
        assert(!memcmp(decoded+15,warning_set+1,7));
        const uint8_t bad_warning[]={2,0,0,0,0x5b,4,0,0,0,20,0,0,0,1,4,0,0,0,200};
        inject(ch,0x8103,bad_warning,sizeof bad_warning);
        assert(msg(ch,&sn,decoded,&len)==1&&decoded[16]==2&&cfg.heartbeat_s==120);
        /* 100 km/h - 10 km/h = 90 km/h. Bit13 stays set across sends,
         * bit1 still waits for the separate configured three seconds. */
        cfg.speed_limit_kmh=100;work_state=WORK_MODE_REALTIME;
        gps.valid=true;gps.fix_quality=1;gps.year=2026;gps.month=10;gps.day=15;
        gps.lat_e7=500000000;gps.lon_e7=100000000;gps.last_update_ms=g_tick_ms;
        gps.speed_kmh=89.9f;scanned_alarms=0;
        scan_alarms();unsigned prior_events=warning_events;
        assert(!(scanned_alarms&ALM_OVERSPEED_WARNING));
        gps.speed_kmh=90.0f;scan_alarms();
        assert((scanned_alarms&ALM_OVERSPEED_WARNING)&&warning_events==prior_events+1);
        scan_alarms();assert(warning_events==prior_events+1);
        for(unsigned repeat=0;repeat<2;++repeat){
            assert(jt808_send_location()==0);
            for(unsigned x=0;x<=3;x+=3){
                assert(msg(x,&sn,decoded,&len)==0x0200);
                assert((decoded[14]&0x20U)&&!(decoded[15]&2U));
            }
        }
        inject(ch,0x8201,NULL,0);
        assert(msg(ch,&sn,decoded,&len)==0x0201&&(decoded[16]&0x20U));
        /* Failed transports persist the warning from the event snapshot. */
        fail_send[0]=fail_send[3]=true;append_result=BLIND_ZONE_OK;
        assert(jt808_send_location_work_mode(ALM_OVERSPEED_WARNING,false,50U+ch)==0);
        assert(appended.length==34U&&(appended.location[2]&0x20U));
        fail_send[0]=fail_send[3]=false;
        /* Falling below the threshold clears even explicitly queued bit13. */
        gps.speed_kmh=89.9f;scan_alarms();
        assert(jt808_send_location_work_mode(ALM_OVERSPEED_WARNING,false,100U+ch)==0);
        assert(msg(ch,&sn,decoded,&len)==0x0200&&!(decoded[14]&0x20U));
        gps.speed_kmh=90.0f;scan_alarms();assert(warning_events==prior_events+2);
        gps.speed_kmh=101.0f;overspeed_policy_init(&s_overspeed_policy);
        scanned_alarms=0;scan_alarms();assert(!(scanned_alarms&ALM_OVERSPEED));
        g_tick_ms+=2999;gps.last_update_ms=g_tick_ms;scan_alarms();
        assert(!(scanned_alarms&ALM_OVERSPEED));
        ++g_tick_ms;gps.last_update_ms=g_tick_ms;scan_alarms();
        assert(scanned_alarms&ALM_OVERSPEED);
        assert(jt808_send_location()==0);
        assert(msg(ch,&sn,decoded,&len)==0x0200&&(decoded[14]&0x20U)&&(decoded[15]&2U));
        /* Invalid, stale, historical and sleeping reports cannot retain bit13. */
        work_state=WORK_MODE_STATIONARY_SLEEP;scan_alarms();
        assert(jt808_send_location()==0);
        assert(msg(ch,&sn,decoded,&len)==0x0200&&!(decoded[14]&0x20U));
        work_state=WORK_MODE_REALTIME;
        assert(jt808_send_location_work_mode(ALM_OVERSPEED_WARNING,true,200U+ch)==0);
        assert(msg(ch,&sn,decoded,&len)==0x0200&&!(decoded[14]&0x20U));
        gps.valid=false;scanned_alarms=0;scan_alarms();assert(!scanned_alarms);
        gps.valid=true;g_tick_ms+=5001;scan_alarms();assert(!scanned_alarms);
        gps.last_update_ms=g_tick_ms;
        cfg.speed_warning_valid=0;scan_alarms();
        assert(jt808_send_location()==0);
        assert(msg(ch,&sn,decoded,&len)==0x0200&&!(decoded[14]&0x20U));
        assert(jt808_send_register_to(ch)==0);assert(msg(ch,&sn,decoded,&len)==0x0100);
        assert(!memcmp(decoded+12,(uint8_t[]){0,44,1,44},4));assert(decoded[48]==2);
        assert(!memcmp(decoded+49,set+sizeof(set)-8,8));
    }
    return 0;
}
'''
    with tempfile.TemporaryDirectory() as d:
        p=Path(d);(p/'h.c').write_text(source + '\n#include "' + (ROOT/'tools/tests/jt808_host_support.h').as_posix() + '"\n',encoding='ascii')
        (p/'n32l40x.h').write_text('#pragma once\n#define GPIOA ((void*)0)\n#define GPIO_PIN_2 2U\n#define GPIO_PIN_12 12U\n#define Bit_RESET 0\nint GPIO_ReadInputDataBit(void*,unsigned);\n')
        cmd=[dual.compiler(),'-std=c99','-Wall','-Wextra','-Werror','-I',str(p),'-I',str(ROOT/'include'),str(p/'h.c')]
        jt_source=ROOT/'src/jt808.c'
        if baseline:
            jt_source=p/'jt808.c';jt_source.write_text(production_source('jt808.c'),encoding='utf-8')
        cmd += [str(jt_source)]
        cmd += [str(ROOT/'src'/s) for s in ['plate_encoding.c','jt808_session.c','terminal_identity.c','jt808_params.c','service_workspace.c','overspeed_policy.c']]
        subprocess.run(cmd+['-lm','-o',str(p/'h.exe')],check=True)
        subprocess.run([str(p/'h.exe')],check=True)
    print('test_jt808_params_wire: PASS')
if __name__=='__main__':main()
