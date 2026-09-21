#!/usr/bin/env python3
from pathlib import Path
import subprocess
import sys
import tempfile

import test_jt808_dual_session as dual

ROOT = Path(__file__).resolve().parents[2]

LOCATION_MAIN = r'''
int main(void) {
    (void)test_rx_overlap; /* shared harness also supplies an independent RX test */
    jt808_terminal_t terminal;
    uint8_t decoded[1024];
    uint16_t sn0, sn3, length, ignored;
    uint32_t status;
    unsigned before0, before3;

    memset(&cfg,0,sizeof(cfg));strcpy(cfg.pid,"56789012345");
    cfg.heartbeat_s=600;cfg.report_moving_s=30;cfg.report_stopped_s=60;
    memset(&terminal,0,sizeof(terminal));memcpy(terminal.manufacturer_id,"CYHLL",5U);
    strcpy(terminal.terminal_model,"A300_406");
    open_ch[0]=open_ch[3]=true;generation[0]=1U;generation[3]=7U;
    jt808_init(&terminal);jt808_set_heartbeat_s(600U);jt808_process();
    assert(msg(0U,&sn0,decoded,&length)==0x0100U);
    assert(msg(3U,&sn3,decoded,&length)==0x0100U);
    reg_resp(0U,sn0,"MAIN-AUTH");jt808_process();assert(msg(0U,&sn0,decoded,&length)==0x0102U);
    reg_resp(3U,sn3,"BACK-AUTH");jt808_process();assert(msg(3U,&sn3,decoded,&length)==0x0102U);
    auth_resp(0U,sn0,0U);auth_resp(3U,sn3,0U);
    assert(jt808_online_mask()==0x09U);

    before0=sends[0];before3=sends[3];
    memset(&gps,0,sizeof(gps));g_tick_ms=100000U;jt808_process();
    assert(sends[0]==before0 && sends[3]==before3);

    gps.valid=true;gps.fix_quality=1U;gps.last_update_ms=g_tick_ms;
    gps.lat=22.543096;gps.lon=114.057865;gps.altitude_m=12.0f;
    gps.speed_kmh=35.0f;gps.heading=91.0f;gps.satellites=12U;
    gps.year=2026U;gps.month=8U;gps.day=31U;
    gps.hour=18U;gps.minute=3U;gps.second=4U;
    work_state=WORK_MODE_STATIONARY_SLEEP;
    fail_send[0]=true;
    jt808_process();
    assert(sends[0]==before0+1U && sends[3]==before3+1U);
    assert(msg(3U,&ignored,decoded,&length)==0x0200U);
    assert(decoded[34U]==0x26U && decoded[35U]==0x09U && decoded[36U]==0x01U);
    assert(decoded[37U]==0x02U && decoded[38U]==0x03U && decoded[39U]==0x04U);
    fail_send[0]=false;
    jt808_process();
    assert(sends[0]==before0+2U && sends[3]==before3+1U);
    jt808_process();
    assert(sends[0]==before0+2U && sends[3]==before3+1U);

    before0=sends[0];before3=sends[3];
    trusted_available=true;
    assert(jt808_send_location_work_mode(0U,true)==0);
    assert(sends[0]==before0+1U && sends[3]==before3+1U);
    assert(msg(3U,&ignored,decoded,&length)==0x0200U);
    status=((uint32_t)decoded[16U]<<24)|((uint32_t)decoded[17U]<<16)|
           ((uint32_t)decoded[18U]<<8)|(uint32_t)decoded[19U];
    assert((status&LOC_FLAG_GPS_FIXED)==0U);
    assert((status&LOC_FLAG_BEIDOU_FIXED)!=0U);

    before0=sends[0];before3=sends[3];
    query(3U,0x8201U);
    assert(sends[0]==before0 && sends[3]==before3+1U);
    assert(msg(3U,&ignored,decoded,&length)==0x0201U);

    gps.last_update_ms=g_tick_ms-5001U;
    g_tick_ms+=60000U;jt808_process();
    assert(sends[0]==before0 && sends[3]==before3+1U);
    return 0;
}
'''

def main() -> int:
    cc=dual.compiler()
    if not cc: return 1
    source=dual.HARNESS[:dual.HARNESS.index("int main(void) {")] + LOCATION_MAIN
    source=source.replace(
        "bool gps_get_last_trusted(gps_data_t *out) { (void)out; return false; }",
        "bool gps_get_last_trusted(gps_data_t *out) { *out=gps; return true; }",
    )
    with tempfile.TemporaryDirectory(prefix="jt808_location_") as directory:
        t=Path(directory);h=t/"h.c";b=t/"h.exe";h.write_text(source,encoding="ascii")
        (t/"n32l40x.h").write_text("#ifndef N32L40X_H\n#define N32L40X_H\n#define GPIOA ((void*)0)\n#define GPIO_PIN_12 12U\n#define Bit_RESET 0\nint GPIO_ReadInputDataBit(void*,unsigned);\n#endif\n",encoding="ascii")
        cmd=[cc,"-std=c99","-Wall","-Wextra","-Werror","-I",str(t),"-I",str(ROOT/"include"),str(h),str(ROOT/"src/jt808.c"),str(ROOT/"src/jt808_session.c"),str(ROOT/"src/terminal_identity.c"),"-lm","-o",str(b)]
        x=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True)
        if x.returncode: print(x.stdout+x.stderr,end="");return x.returncode
        x=subprocess.run([str(b)],cwd=ROOT,capture_output=True,text=True)
        if x.returncode: print(x.stdout+x.stderr,end="");return x.returncode
    print("test_jt808_first_location: PASS");return 0

if __name__=="__main__":sys.exit(main())
