"""Real work-mode/params/FREQ -> gps.c -> dual-channel 0200 sleep cadence."""
from pathlib import Path
import subprocess
import tempfile
import test_gps_ntp_apply as gps_fixture
import test_jt808_dual_session as dual

ROOT = Path(__file__).resolve().parents[2]
MAIN = r'''
#include <stdio.h>
#include "f39_command.h"
#include "f39_config_adapter.h"
uint32_t work_mode_sleep_monotonic_s(void) { return g_tick_ms/1000U; }
void tcp_manager_request_reconnect(void) {}
void tcp_manager_reconnect_channels(uint8_t mask) { (void)mask; }
void ec800m_restart_pdp(void) {}
static bool persist(const device_config_t *c, void *ctx) {
    (void)ctx; return cfg_store_candidate(c);
}
static void dispatch(void) {
    work_mode_action_t a;
    unsigned count=0;
    while (work_mode_next_action(&a)) {
        assert(++count<=8);
        if (a.type==WORK_ACTION_SET_LOGICAL_ACC) jt808_set_logical_acc(a.acc_on);
        if (a.type==WORK_ACTION_REPORT_LOCATION || a.type==WORK_ACTION_REPORT_ENTRY)
            assert(jt808_send_location_work_mode(a.alarm_bits,a.historical_position,a.report_id)==0);
    }
}
static void step(unsigned now_s) {
    g_tick_ms=now_s*1000U;
    work_mode_input_t in={0}; in.now_s=now_s;
    work_mode_step(&in); dispatch();
    assert(work_mode_state()==WORK_MODE_STATIONARY_SLEEP);
}
static void check_report(unsigned hour, unsigned minute, unsigned second) {
    uint8_t d[1024]; uint16_t sn,n;
    unsigned t[]={26,10,5,hour,minute,second};
    for (unsigned ch=0;ch<=3;ch+=3) {
        assert(msg(ch,&sn,d,&n)==0x0200);
        assert(!(d[19]&3)); /* ACC OFF, retained position, no current fix */
        assert(d[20]==0 && d[21]==0x98 && d[22]==0x96 && d[23]==0x80);
        for(unsigned i=0;i<6;++i) {
            unsigned expected=(t[i]/10)<<4 | t[i]%10;
            if(d[34+i]!=expected)
                fprintf(stderr,"sleep 0200 UTC field %u: got %02x expected %02x at %lu s\n",
                        i,d[34+i],expected,(unsigned long)work_mode_sleep_monotonic_s());
            assert(d[34+i]==expected);
        }
    }
}
static void freq(const char *text) {
    f39_request_t request; f39_transaction_t tx;
    /* The SMS ingress consumes the '#' terminator before f39_parse(). */
    unsigned length=strlen(text); assert(length && text[length-1]=='#');
    assert(f39_parse((const uint8_t *)text,length-1,&request)==F39_RESULT_OK);
    f39_transaction_init(&tx,&cfg,persist,NULL);
    assert(f39_prepare_config(&request,&cfg,&tx));
    assert(tx.effects & F39_EFFECT_TIMER_REFRESH);
    assert(f39_commit_config(&tx)==F39_RESULT_OK);
    work_mode_config_changed(&cfg,work_mode_sleep_monotonic_s());
}
int main(void) {
    (void)test_rx_overlap; (void)reg_resp; (void)feed;
    jt808_terminal_t terminal={0}; uint8_t d[1024]; uint16_t sn,n;
    strcpy(cfg.pid,"56789012345"); strcpy(cfg.auth_code,"TEST");
    strcpy(cfg.backup_auth_code,"TEST"); cfg.heartbeat_s=180;
    cfg.report_moving_s=30; cfg.report_stopped_s=300;
    open_ch[0]=open_ch[3]=true; jt808_init(&terminal); jt808_process();
    for(unsigned ch=0;ch<=3;ch+=3) { msg(ch,&sn,d,&n); auth_resp(ch,sn,0); }
    gps_data_t fix={0}; fix.valid=true; fix.fix_quality=1;
    fix.lat=10; fix.lon=20; fix.year=2026; fix.month=10; fix.day=5;
    fix.hour=0; fix.last_update_ms=0;
    assert(gps_capture_last_trusted_snapshot(&fix));
    work_mode_init(NULL,0,true); dispatch();
    step(0); check_report(8,0,0);
    unsigned before=sends[0]; step(299); assert(sends[0]==before);
    step(300); assert(sends[0]==before+1); check_report(8,5,0);
    step(300); assert(sends[0]==before+1);
    step(600); check_report(8,10,0);
    /* A platform 8103 interval change reaches the live sleep scheduler. */
    const uint8_t set[]={1,0,0,0,0x27,4,0,0,0,60};
    inject(0,0x8103,set,sizeof set); assert(msg(0,&sn,d,&n)==1 && d[16]==0);
    before=sends[0]; step(659); assert(sends[0]==before);
    step(660); assert(sends[0]==before+1); check_report(8,11,0);
    freq("FREQ,30,300#"); before=sends[0]; step(959); assert(sends[0]==before);
    step(960); assert(sends[0]==before+1); check_report(8,16,0);
    /* FREQ re-enables reporting after explicit GPSDUP suppression. */
    freq("GPSDUP,0#"); before=sends[0]; step(1260); assert(sends[0]==before);
    freq("FREQ,30,120#"); step(1379); assert(sends[0]==before);
    step(1380); assert(sends[0]==before+1); check_report(8,23,0);
    /* No-fix outside sleep keeps acquisition UTC, including 0201 queries. */
    gps_data_t location; assert(gps_get_last_trusted_location(&location));
    assert(location.hour==0 && location.minute==0 && location.second==0);
    assert(jt808_send_location_work_mode(0,false,998)==0); check_report(8,0,0);
    query(0,0x8201); assert(msg(0,&sn,d,&n)==0x0201 && d[37]==0x08 && d[38]==0);
    /* A pending NOR record keeps the same event timestamp across retries. */
    open_ch[0]=open_ch[3]=false; append_result=BLIND_ZONE_BUSY;
    assert(jt808_send_location_work_mode(0,true,999)==-2);
    uint8_t saved[34]; memcpy(saved,appended.location,34);
    g_tick_ms+=20000; append_result=BLIND_ZONE_OK;
    assert(jt808_send_location_work_mode(0,true,999)==0);
    assert(!memcmp(saved,appended.location,34));
    assert(jt808_send_location_work_mode(0,true,1000)==0);
    assert(appended.location[27]==0x20);
    /* STOP1's RTC contribution advances time while SysTick is suspended. */
    gps_advance_last_trusted_seconds(15);
    assert(jt808_send_location_work_mode(0,true,1001)==0);
    assert(appended.location[26]==0x23 && appended.location[27]==0x35);
    return 0;
}
'''


def main():
    source = dual.HARNESS.split('int main(void) {')[0]
    start = source.index('void jt808_params_handle_set(')
    end = source.index('jt808_terminal_info_result_t jt808_terminal_info_encode(', start)
    source = source[:start] + source[end:]
    source = '\n'.join(line for line in source.splitlines() if not line.startswith((
        'const gps_data_t *gps_get_data(', 'bool gps_get_last_trusted(',
        'static bool trusted_available;', 'static gps_data_t gps;',
        'static work_mode_state_t work_state', 'work_mode_state_t work_mode_state(')))
    source += '\n#define HOST_REAL_GPS\n#include "' + (ROOT/'tools/tests/jt808_host_support.h').as_posix() + '"\n'
    hardware = 'void GPIO_InitStruct' + gps_fixture.HARNESS.split('void GPIO_InitStruct')[1].split('int main(void)')[0]
    hardware = '\n'.join(line for line in hardware.splitlines() if not line.startswith('int dbg_printf('))
    with tempfile.TemporaryDirectory(prefix='sleep_location_') as td:
        d = Path(td)
        (d/'h.c').write_text(source+'\n#include "n32l40x.h"\n'+hardware+MAIN, encoding='ascii')
        (d/'n32l40x.h').write_text(gps_fixture.N32, encoding='ascii')
        (d/'hw_init.h').write_text('#include <stdbool.h>\nvoid delay_ms(uint32_t);\nbool hw_acc_is_on(void);\n', encoding='ascii')
        sources = ['gps.c','jt808.c','jt808_session.c','terminal_identity.c','plate_encoding.c',
                   'work_mode.c','jt808_params.c','service_workspace.c','f39_command.c','f39_config_adapter.c']
        subprocess.run([dual.compiler(),'-std=c99','-Wall','-Wextra','-Werror',
                        '-ffunction-sections','-Wl,--gc-sections','-I',str(d),'-I',str(ROOT/'include'),
                        str(d/'h.c'),*[str(ROOT/'src'/s) for s in sources],'-lm','-o',str(d/'h.exe')],
                       check=True, timeout=60)
        subprocess.run([str(d/'h.exe')],check=True,timeout=30)
    print('test_sleep_location_reporting: PASS')


if __name__ == '__main__':
    main()
