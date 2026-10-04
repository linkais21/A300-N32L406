"""Execute the real local production command handler with GPIO/driver fixtures."""
from pathlib import Path
import subprocess
import tempfile
import argparse
from test_f39_actions import find_compiler

ROOT = Path(__file__).resolve().parents[2]
HEADERS = {
    'config.h': '#include <stdint.h>\nextern volatile uint32_t g_tick_ms;\n#define TICK_MS() g_tick_ms\n#define SOS_PORT 0\n#define SOS_PIN 2\n#define RELAY_PORT 0\n#define RELAY_PIN 11\n#define DA218E_INT1_PORT 0\n#define DA218E_INT1_PIN 3\n',
    'n32l40x.h': 'int GPIO_ReadInputDataBit(int,int);\n#define Bit_RESET 0\n',
    'hw_init.h': '#include <stdbool.h>\nbool hw_acc_is_on(void);\n',
    'work_mode.h': '#include <stdbool.h>\nbool work_mode_logical_acc(void);\n',
    'debug_uart.h': 'int dbg_printf(const char*,...);\n',
    'adc_monitor.h': '#include <stdbool.h>\nbool adc_monitor_valid(void);\nfloat adc_get_car_voltage(void);\nfloat adc_get_bat_voltage(void);\n',
    'i2c_accel.h': '#include <stdint.h>\n#include <stdbool.h>\ntypedef struct {int16_t x,y,z;} accel_data_t;\nbool i2c_accel_read(accel_data_t*);\n',
    'relay.h': '#include <stdbool.h>\n#include <stdint.h>\nbool relay_get(void);\nvoid relay_set(bool);\nbool relay_test_low(void);\nvoid relay_test_high(void);\nuint16_t relay_test_remaining(void);\n',
    'gps.h': '#include <stdbool.h>\n#include <stdint.h>\ntypedef struct {bool valid; uint8_t fix_quality,satellites; float hdop; uint32_t last_update_ms,quality_update_ms;} gps_data_t;\ntypedef struct {uint8_t satellites,average,maximum; uint32_t sequence;} gps_quality_t;\nbool gps_quality_fix_fresh(void);\nconst gps_data_t *gps_get_data(void);\nbool gps_get_quality(gps_quality_t*);\n',
}
HARNESS = r'''
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include "production_test.h"
#include "gps.h"
#include "i2c_accel.h"
volatile uint32_t g_tick_ms;
static bool acc, sos, adc_ok, accel_ok=true, low, quality_ok;
static char reply[512];
static gps_data_t gps;
static gps_diag_t diag;
static unsigned trace_calls;
void gps_trace_start(void){++trace_calls;}
const volatile gps_diag_t *gps_get_diag(void){return &diag;}
int dbg_printf(const char *fmt,...) {va_list a;va_start(a,fmt);int n=vsnprintf(reply,sizeof reply,fmt,a);va_end(a);return n;}
int GPIO_ReadInputDataBit(int p,int pin){(void)p;return pin==2?!sos:low;}
bool hw_acc_is_on(void){return acc;}
bool work_mode_logical_acc(void){return false;}
bool adc_monitor_valid(void){return adc_ok;}
float adc_get_car_voltage(void){return 12.0f;}
float adc_get_bat_voltage(void){return 3.7f;}
bool i2c_accel_read(accel_data_t *v){v->x=-123;v->y=45;v->z=678;return accel_ok;}
bool relay_get(void){return low;}
void relay_set(bool v){low=v;}
bool relay_test_low(void){if(low)return false;low=true;return true;}
void relay_test_high(void){low=false;}
uint16_t relay_test_remaining(void){return low?3000:0;}
const gps_data_t *gps_get_data(void){return &gps;}
bool gps_get_quality(gps_quality_t *q){q->satellites=8;q->average=35;q->maximum=42;q->sequence=7;return quality_ok;}
bool gps_quality_fix_fresh(void){return gps.valid && (uint32_t)(g_tick_ms-gps.quality_update_ms)<=5000 && (uint32_t)(g_tick_ms-gps.last_update_ms)<=5000;}
static void query(const char *s,const char *want){reply[0]=0;assert(production_test_command(s));if(!strstr(reply,want)){puts(reply);assert(0);}fputs(reply,stdout);}
static void ticks(unsigned n){while(n--){++g_tick_ms;production_test_tick();}}
int main(void){
 query("GNSSRAW#","MAX=32,WINDOW_MS=5000");assert(trace_calls==1);
 diag.gsv_seen=12;diag.gsv_complete=3;
 query("GNSSDIAG#","GSV=12,COMPLETE=3,QUEUE_DROP=0");
 assert(!production_test_command("RELAY,1#"));
 query("FACTORYCAP#","TTS=0,RS485=0");
 query("ACCSTAT#","DEB=0");acc=true;ticks(49);query("ACCSTAT#","DEB=0");ticks(1);query("ACCSTAT#","DEB=1");
 acc=false;ticks(30);acc=true;ticks(30);query("ACCSTAT#","DEB=1");
 query("GSENSOR#","X=-123,Y=45,Z=678");accel_ok=false;query("GSENSOR#","=Fail!");
 query("STATUS#","ADC_NOT_READY");adc_ok=true;query("STATUS#","VCAR=12000,VBAT=3700,VALID=1");
 query("SOSSTAT#","DOWN=0,HOLD_MS=0");sos=true;ticks(1999);query("SOSSTAT#","HOLD_MS=1999");ticks(1);query("SOSSTAT#","HOLD_MS=2000");sos=false;ticks(1);query("SOSSTAT#","HOLD_MS=0");
 g_tick_ms=0xfffffffeU;ticks(4);query("SOSSTAT#","DOWN=0");
 query("RELAYTEST,LOW,EXTRA#","=Fail!");assert(!low);
 query("RELAYTEST,LOW#","OUT=LOW,MCU=1,PAD=1");query("RELAYTEST,LOW#","BUSY");
 query("RELAYTEST,HIGH#","OUT=HIGH,MCU=0,PAD=0");
 query("GNSSSTAT#","FIX=0");quality_ok=true;gps.valid=true;gps.fix_quality=1;gps.satellites=8;gps.hdop=0.9f;gps.last_update_ms=g_tick_ms;
 query("GNSSSTAT#","FIX=1,GPS=8,HDOP=0.9,CNSAT=8,CNAVG=35,CNMAX=42,SEQ=7");
 g_tick_ms+=6000;query("GNSSSTAT#","FIX=0");
 gps.last_update_ms=g_tick_ms;query("GNSSSTAT#","FIX=0");
 sos=true;ticks(6000);query("SOSSTAT#","DOWN=1,HOLD_MS=0");
 sos=false;ticks(1);query("SOSSTAT#","DOWN=0,HOLD_MS=0");
 puts("production commands PASS");return 0;
}
'''

HEADERS['gps.h'] += 'typedef struct {uint32_t rx_bytes,gga,rmc,gsv_seen,gsv_complete,drop_queue,drop_length,checksum_fail,overrun;} gps_diag_t;\nvoid gps_trace_start(void);\nconst volatile gps_diag_t *gps_get_diag(void);\n'

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--wire-output',type=Path)
    args=parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='production-test-') as tmp:
        p=Path(tmp)
        for name,body in HEADERS.items(): (p/name).write_text(body)
        (p/'test.c').write_text(HARNESS)
        subprocess.run([find_compiler(),'-std=c99','-Wall','-Wextra','-Werror','-I',str(p),'-I',str(ROOT/'include'),str(p/'test.c'),str(ROOT/'src/production_test.c'),'-o',str(p/'test.exe')],check=True)
        run=subprocess.run([str(p/'test.exe')],capture_output=True,text=True)
        if run.returncode:
            print(run.stdout+run.stderr)
            run.check_returncode()
        if args.wire_output:
            args.wire_output.write_text('\n'.join(line for line in run.stdout.splitlines() if '=Success!' in line or '=Fail!' in line)+'\n',encoding='utf-8')
        print(run.stdout.splitlines()[-1])

if __name__ == '__main__': main()
