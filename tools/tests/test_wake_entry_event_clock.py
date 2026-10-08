"""Real ACC/vibration transitions -> dispatcher call -> GPS -> JT808 wire."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import test_gps_ntp_apply as gps_fixture
import test_jt808_dual_session as dual

ROOT = Path(__file__).resolve().parents[2]
MAIN = r'''
#include <stdio.h>
static void dispatch(void) {
    work_mode_action_t action;
    unsigned count=0;
    while (work_mode_next_action(&action)) {
        assert(++count<=8);
        if (action.type==WORK_ACTION_SET_LOGICAL_ACC) jt808_set_logical_acc(action.acc_on);
        if (action.type==WORK_ACTION_GPS_ON) { gps_enable(true); gps_resume_after_wake(); }
        if (action.type==WORK_ACTION_REPORT_ENTRY || action.type==WORK_ACTION_REPORT_LOCATION) {
            int sent;
            DISPATCH_SEND_STATEMENT
            assert(sent==0);
        }
    }
}
static void check_clock(unsigned minute, unsigned second) {
    uint8_t d[1024]; uint16_t sn,n;
    uint8_t expected[]={0x26,0x10,0x07,0x08,(uint8_t)((minute/10)*16+minute%10),
                        (uint8_t)((second/10)*16+second%10)};
    for(unsigned ch=0;ch<=3;ch+=3) {
        assert(msg(ch,&sn,d,&n)==0x0200);
        if(memcmp(d+34,expected,6)) {
            fprintf(stderr,"wake entry clock goes backwards: channel=%u got=%02x:%02x:%02x expected=%02x:%02x:%02x\n",
                    ch,d[37],d[38],d[39],expected[3],expected[4],expected[5]);
        }
        assert(!memcmp(d+34,expected,6));
        assert((d[19]&3)==1); /* logical ACC ON, current fix clear */
        assert(d[20]==0 && d[21]==0x98 && d[22]==0x96 && d[23]==0x80);
    }
}
static void step(uint32_t ms, bool acc, bool sample, bool hit) {
    g_tick_ms=ms;
    work_mode_input_t in={0}; in.now_ms=ms; in.now_s=ms/1000;
    in.acc_high=acc; in.vibration_sample_valid=sample; in.vibration_hit=hit;
    work_mode_step(&in); dispatch();
}
int main(int argc, char **argv) {
    (void)test_rx_overlap; (void)reg_resp; (void)query; (void)feed;
    assert(argc==2);
    jt808_terminal_t terminal={0}; uint8_t d[1024]; uint16_t sn,n;
    strcpy(cfg.pid,"56789012345"); strcpy(cfg.auth_code,"TEST");
    strcpy(cfg.backup_auth_code,"TEST"); cfg.heartbeat_s=600;
    open_ch[0]=open_ch[3]=true; jt808_init(&terminal); jt808_process();
    for(unsigned ch=0;ch<=3;ch+=3) { msg(ch,&sn,d,&n); auth_resp(ch,sn,0); }
    if(!strcmp(argv[1],"cold")) {
        /* NTP provides event time without fabricating coordinates or a fix. */
        gps_apply_ntp_utc(2026,10,7,0,1,0); g_tick_ms+=2000;
        jt808_set_logical_acc(true);
        work_mode_action_t action={0}; action.type=WORK_ACTION_REPORT_ENTRY;
        action.acc_on=true; action.report_id=1;
        int sent;
        DISPATCH_SEND_STATEMENT
        assert(sent==0 && msg(0,&sn,d,&n)==0x0200 && (d[19]&3)==1);
        assert(d[38]==0x01 && d[39]==0x02);
        for(unsigned i=20;i<28;++i) assert(d[i]==0);
        assert(!gps_is_valid());
        return 0;
    }
    gps_data_t fix={0}; fix.valid=true; fix.fix_quality=1;
    fix.lat=10; fix.lon=20; fix.year=2026; fix.month=10; fix.day=7;
    assert(gps_capture_last_trusted_snapshot(&fix));
    work_mode_config_t c={30,300,600,300,6};
    work_mode_init(&c,0,false); dispatch();
    /* Sleep entry at 5min has advanced time. Its next wake must not return to 0min. */
    g_tick_ms=300000;
    work_mode_input_t in={0}; in.now_s=300; in.gps_valid=true;
    work_mode_step(&in); dispatch(); assert(work_mode_state()==WORK_MODE_STATIONARY_SLEEP);
    unsigned before=sends[0];
    if(!strcmp(argv[1],"acc")) {
        work_mode_acc_sample(true,360000); step(360000,true,false,false);
        assert(work_mode_state()==WORK_MODE_STATIONARY_SLEEP && sends[0]==before);
        work_mode_acc_sample(true,360500); step(360500,true,false,false);
        assert(work_mode_state()==WORK_MODE_REALTIME); check_clock(6,0);
    } else {
        assert(!strcmp(argv[1],"vibration"));
        for(unsigned i=0;i<=30;++i) step(360000+i*200,false,true,true);
        assert(work_mode_state()==WORK_MODE_REALTIME); check_clock(6,6);
        assert(!hw_acc_is_on()); /* logical ACC still encoded ON */
    }
    assert(sends[0]==before+1 && sends[3]>=sends[0]);
    unsigned repeat_count=sends[0]; uint32_t now=g_tick_ms;
    step(now+1,!strcmp(argv[1],"acc"),false,false); assert(sends[0]==repeat_count);
    /* Second, third and fourth scheduled packets must continue event UTC;
     * the mode-entry-only fix otherwise returns to old acquisition time. */
    unsigned wake_s=now/1000U;
    for(unsigned i=1;i<=3;++i) {
        unsigned expected_s=wake_s+30*i;
        step(expected_s*1000U,!strcmp(argv[1],"acc"),false,false);
        assert(sends[0]==repeat_count+i);
        check_clock(expected_s/60U,expected_s%60U);
    }
    /* New no-fix 0200 events advance; 0201 keeps location acquisition UTC. */
    assert(jt808_send_location_work_mode(0,false,900)==0);
    check_clock((wake_s+90)/60U,(wake_s+90)%60U);
    query(0,0x8201); assert(msg(0,&sn,d,&n)==0x0201 && d[38]==0 && d[39]==0);
    /* Offline event transaction keeps its original timestamp and ACC during retry. */
    open_ch[0]=open_ch[3]=false; append_result=BLIND_ZONE_BUSY;
    work_mode_action_t action={0}; action.type=WORK_ACTION_REPORT_ENTRY;
    action.acc_on=true; action.report_id=901;
    int sent;
    DISPATCH_SEND_STATEMENT
    assert(sent==-2); uint8_t saved[34]; memcpy(saved,appended.location,34);
    assert((saved[7]&3)==1);
    g_tick_ms+=20000; append_result=BLIND_ZONE_OK;
    DISPATCH_SEND_STATEMENT
    assert(sent==0 && !memcmp(saved,appended.location,34));
    /* A fresh fix is still reported with real current-fix status. */
    open_ch[0]=open_ch[3]=true;
    static const char *gga="GNGGA,000900.000,1000.0000,N,02000.0000,E,1,08,0.9,1.0,M,0.0,M,,";
    static const char *rmc="GNRMC,000900.000,A,1000.0000,N,02000.0000,E,0.0,0.0,071026,,,A";
    feed_sentence(gga); gps_process(); feed_sentence(rmc); gps_process();
    before=sends[0]; in.now_ms=g_tick_ms; in.now_s=g_tick_ms/1000;
    in.acc_high=true; in.gps_valid=true;
    work_mode_step(&in); dispatch(); assert(sends[0]==before+1);
    assert(msg(0,&sn,d,&n)==0x0200 && (d[19]&3)==3);
    work_mode_step(&in); dispatch(); assert(sends[0]==before+1);
    return 0;
}
'''

def main():
    # Compile the exact report selection statement from the production dispatcher.
    main_source=(ROOT/'src/main.c').read_text(encoding='utf-8')
    section=main_source.split('case WORK_ACTION_REPORT_ENTRY:')[1]
    statement=re.search(r'\bsent\s*=.*?;',section,re.S).group(0)
    source=dual.HARNESS.split('int main(void) {')[0]
    source='\n'.join(line for line in source.splitlines() if not line.startswith((
        'const gps_data_t *gps_get_data(', 'bool gps_get_last_trusted(',
        'static bool trusted_available;', 'static gps_data_t gps;',
        'static work_mode_state_t work_state', 'work_mode_state_t work_mode_state(')))
    source+='\n#define HOST_REAL_GPS\n#include "'+(ROOT/'tools/tests/jt808_host_support.h').as_posix()+'"\n'
    hardware='void GPIO_InitStruct'+gps_fixture.HARNESS.split('void GPIO_InitStruct')[1].split('int main(void)')[0]
    hardware='\n'.join(line for line in hardware.splitlines() if not line.startswith('int dbg_printf('))
    with tempfile.TemporaryDirectory(prefix='wake_entry_') as td:
        d=Path(td)
        (d/'h.c').write_text(source+'\n#include "n32l40x.h"\n'+hardware+MAIN.replace('DISPATCH_SEND_STATEMENT',statement),encoding='ascii')
        (d/'n32l40x.h').write_text(gps_fixture.N32,encoding='ascii')
        (d/'hw_init.h').write_text('#include <stdbool.h>\nvoid delay_ms(uint32_t);\nbool hw_acc_is_on(void);\n',encoding='ascii')
        files=['gps.c','jt808.c','jt808_session.c','terminal_identity.c','plate_encoding.c','work_mode.c']
        subprocess.run([dual.compiler(),'-std=c99','-Wall','-Wextra','-Werror',
                        '-I',str(d),'-I',str(ROOT/'include'),str(d/'h.c'),
                        *[str(ROOT/'src'/f) for f in files],'-lm','-o',str(d/'h.exe')],check=True,timeout=60)
        results=[]
        for scenario in ('acc','vibration','cold'):
            run=subprocess.run([str(d/'h.exe'),scenario],capture_output=True,timeout=30)
            print(scenario,'PASS' if run.returncode==0 else 'FAIL')
            if run.returncode: print((run.stdout+run.stderr).decode(errors='replace'))
            results.append(run.returncode)
        if any(results): return 1
    print('test_wake_entry_event_clock: PASS')
    return 0

if __name__=='__main__':
    sys.exit(main())
