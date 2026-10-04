"""Actual gps.c -> jt808.c wire time, including immutable blind-zone events."""
from pathlib import Path
import subprocess
import tempfile
import test_gps_ntp_apply as gps_fixture
import test_jt808_dual_session as dual

ROOT = Path(__file__).resolve().parents[2]
MAIN = r'''
int main(void) {
    (void)test_rx_overlap; (void)query; (void)feed;
    jt808_terminal_t t={0}; uint8_t d[1024]; uint16_t sn0,sn3,n;
    strcpy(cfg.pid,"56789012345"); cfg.heartbeat_s=600;
    strcpy(t.terminal_model,"A300_406"); memcpy(t.manufacturer_id,"70110",5);
    open_ch[0]=open_ch[3]=true; generation[0]=generation[3]=1;
    jt808_init(&t); jt808_process();
    msg(0,&sn0,d,&n); msg(3,&sn3,d,&n);
    reg_resp(0,sn0,"TEST"); jt808_process(); msg(0,&sn0,d,&n);
    reg_resp(3,sn3,"TEST"); jt808_process(); msg(3,&sn3,d,&n);
    auth_resp(0,sn0,0); auth_resp(3,sn3,0);
    /* Retain an invented test fix; live GNSS remains invalid throughout. */
    gps_data_t fix={0}; fix.valid=true; fix.fix_quality=1;
    fix.lat=10; fix.lon=20; fix.year=2026; fix.month=9; fix.day=20;
    fix.hour=5; fix.minute=47; fix.second=52; fix.last_update_ms=g_tick_ms;
    assert(gps_capture_last_trusted_snapshot(&fix));
    for(unsigned i=1; i<=3; ++i) {
        g_tick_ms+=10000;
        assert(jt808_send_location_work_mode(0,false,i)==0);
        for(unsigned ch=0; ch<=3; ch+=3) {
            assert(msg(ch,&sn0,d,&n)==0x0200);
            const uint8_t expected[]={0x26,0x09,0x20,0x13,0x48,
                (uint8_t)(((i-1)<<4)|2)};
            assert(memcmp(d+34,expected,6)==0);
            assert(!(d[19]&2)); /* position is historical, not a current fix */
        }
    }
    /* A blind-zone record keeps its event time while its append is retried. */
    open_ch[0]=open_ch[3]=false;
    append_result=BLIND_ZONE_BUSY;
    assert(jt808_send_location_work_mode(0,false,4)==-2);
    uint8_t saved[34]; memcpy(saved,appended.location,34);
    g_tick_ms+=20000;
    append_result=BLIND_ZONE_OK;
    assert(jt808_send_location_work_mode(0,false,4)==0);
    assert(memcmp(saved,appended.location,34)==0);
    assert(jt808_send_location_work_mode(0,false,5)==0);
    assert(appended.location[27]==0x42);
    return 0;
}
'''

def main():
    source = dual.HARNESS.split('int main(void) {')[0]
    source += '\n#define HOST_REAL_GPS\n#include "' + (ROOT/'tools/tests/jt808_host_support.h').as_posix() + '"\n'
    source = '\n'.join(line for line in source.splitlines()
                       if not line.startswith(('const gps_data_t *gps_get_data(',
                                               'bool gps_get_last_trusted(',
                                               'static bool trusted_available;',
                                               'static gps_data_t gps;')))
    hardware = gps_fixture.HARNESS.split('void GPIO_InitStruct')[1].split('int main(void)')[0]
    hardware = 'void GPIO_InitStruct' + hardware
    hardware = '\n'.join(line for line in hardware.splitlines()
                         if not line.startswith('int dbg_printf('))
    with tempfile.TemporaryDirectory(prefix='jt808_nofix_') as td:
        d=Path(td)
        (d/'h.c').write_text(source+'\n#include "n32l40x.h"\n'+hardware+MAIN, encoding='ascii')
        (d/'n32l40x.h').write_text(gps_fixture.N32, encoding='ascii')
        (d/'hw_init.h').write_text('#include <stdbool.h>\nvoid delay_ms(uint32_t);\nbool hw_acc_is_on(void);\n', encoding='ascii')
        # jt808.c needs the normal debug macros; gps.c also uses this header.
        sources=['gps.c','jt808.c','jt808_session.c','terminal_identity.c','plate_encoding.c']
        subprocess.run([dual.compiler(),'-std=c99','-Wall','-Wextra','-Werror',
                        '-I',str(d),'-I',str(ROOT/'include'),str(d/'h.c'),
                        *[str(ROOT/'src'/s) for s in sources],'-lm','-o',str(d/'h.exe')],
                       check=True, timeout=60)
        subprocess.run([str(d/'h.exe')],check=True,timeout=30)
    print('test_jt808_nofix_clock: PASS')

if __name__=='__main__':
    main()
