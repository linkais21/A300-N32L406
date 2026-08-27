"""Compile/execute C harness for AGNSS stream reset and malformed handling."""
from pathlib import Path
import shutil, subprocess, tempfile

ROOT = Path(__file__).resolve().parents[2]

def test_c_harness():
    cc = shutil.which("gcc") or shutil.which("cc")
    if not cc:
        if __import__('os').environ.get('REQUIRE_GCC') == '1':
            raise AssertionError('REQUIRE_GCC=1 but no gcc/cc found')
        print("test_agnss_vendor_stream: SKIP (gcc unavailable)")
        return
    with tempfile.TemporaryDirectory() as td:
        t = Path(td)
        (t / "agnss_storage.h").write_text('#ifndef AGNSS_STORAGE_H\n#define AGNSS_STORAGE_H\n#include <stdint.h>\ntypedef enum { GNSS_TYPE_UNKNOWN=0,GNSS_TYPE_TAU804M=1,GNSS_TYPE_ATGM332D_F7N=2 } gnss_type_t;\n#endif\n', encoding='utf-8')
        (t / "gps.h").write_text('#ifndef GPS_H\n#define GPS_H\n#include <stdint.h>\n#include <stdbool.h>\ntypedef struct { double lat,lon; float altitude_m; uint16_t year; uint8_t month,day,hour,minute,second; bool valid; } gps_data_t; typedef gps_data_t gps_context_t; int gps_send_raw(const uint8_t*,uint32_t); const gps_data_t *gps_get_data(void);\n#endif\n', encoding='utf-8')
        (t / "agnss_vendor.h").write_text('#ifndef AGNSS_VENDOR_H\n#define AGNSS_VENDOR_H\n#include <stdint.h>\n#include <stdbool.h>\n#include "agnss_storage.h"\n#include "gps.h"\ntypedef struct { const uint8_t *data; uint32_t len; } agnss_source_t; typedef enum { ZK_RESP_MALFORMED=-1,ZK_RESP_INCOMPLETE=0,ZK_RESP_OK=1 } zhongkewei_resp_t; int agnss_huada_inject(const agnss_source_t*,const gps_context_t*); int agnss_zhongkewei_request(const agnss_source_t*,const gps_context_t*); zhongkewei_resp_t zhongkewei_parse_response(const uint8_t*,uint32_t,const uint8_t**,uint16_t*);\n#endif\n', encoding='utf-8')
        (t / "debug_uart.h").write_text('#ifndef DEBUG_UART_H\n#define DEBUG_UART_H\n#endif\n', encoding='utf-8')
        (t / "ec800m.h").write_text('#ifndef EC800M_H\n#define EC800M_H\n#include <stdint.h>\n#include <stdbool.h>\n#define EC800M_CH_AGPS 2\ntypedef enum { TCP_STATE_CLOSED=0,TCP_STATE_OPEN=2 } tcp_state_t; bool ec800m_is_ready(void); tcp_state_t ec800m_tcp_state(uint8_t); int ec800m_tcp_send(uint8_t,const uint8_t*,uint16_t);\n#endif\n', encoding='utf-8')
        (t / "fota.h").write_text('#ifndef FOTA_H\n#define FOTA_H\ntypedef enum { FOTA_STATE_IDLE=0,FOTA_STATE_CONNECTING,FOTA_STATE_DOWNLOADING,FOTA_STATE_VERIFYING } fota_state_t; fota_state_t fota_get_state(void);\n#endif\n', encoding='utf-8')
        (t / "flash_config.h").write_text('#ifndef FLASH_CONFIG_H\n#define FLASH_CONFIG_H\ntypedef struct { char agnss_user[64],agnss_pwd[64]; } device_config_t; device_config_t *cfg_get(void);\n#endif\n', encoding='utf-8')
        (t / "harness.c").write_text(r'''
#include <assert.h>
#include "agnss_vendor.h"
#include "flash_config.h"
#include "ec800m.h"
#include "fota.h"
static int fail_uart; static gps_data_t g={0}; static device_config_t c={"u","p"};
int gps_send_raw(const uint8_t*p,uint32_t n){(void)p;(void)n;return fail_uart?-1:0;} const gps_data_t*gps_get_data(void){return &g;}
fota_state_t fota_get_state(void){return FOTA_STATE_IDLE;} bool ec800m_is_ready(void){return true;} tcp_state_t ec800m_tcp_state(uint8_t c){(void)c;return TCP_STATE_OPEN;} int ec800m_tcp_send(uint8_t c,const uint8_t*p,uint16_t n){(void)c;(void)p;(void)n;return 0;} device_config_t*cfg_get(void){return &c;}
#include "agnss_huada.c"
#include "agnss_zhongkewei.c"
int main(void){uint8_t f[8]={0xf1,0xd9,0x0b,0x10,1,0,0x7a,0}; fail_uart=1; assert(agnss_huada_inject(&(agnss_source_t){f,8},&(gps_context_t){0})<0); fail_uart=0; f[4]=0xff;f[5]=0xff; assert(agnss_huada_inject(&(agnss_source_t){f,8},&(gps_context_t){0})<0); f[4]=1;f[5]=0; assert(agnss_huada_inject(&(agnss_source_t){f,8},&(gps_context_t){0})==0); const uint8_t*p;uint16_t n; assert(zhongkewei_parse_response((const uint8_t*)"A",1,&p,&n)==ZK_RESP_INCOMPLETE); assert(zhongkewei_parse_response((const uint8_t*)"XX",2,&p,&n)==ZK_RESP_MALFORMED); return 0;}
''', encoding='utf-8')
        out=t/'harness.exe'; b=subprocess.run([cc,'-std=c99','-I',str(t),'-I',str(ROOT/'src'),str(t/'harness.c'),'-o',str(out),'-lm'],cwd=ROOT,capture_output=True,text=True)
        if b.returncode: raise AssertionError('C harness compile failed:\n'+b.stderr)
        assert subprocess.run([str(out)]).returncode == 0

if __name__ == '__main__': test_c_harness(); print('test_agnss_vendor_stream: PASS')
