"""Compare production location encoders byte-for-byte with a supplied baseline."""
from pathlib import Path
import argparse
import re
import shutil
import subprocess
import tempfile
from test_location_numeric_equivalence import function

ROOT = Path(__file__).resolve().parents[2]


def encoder(source, prefix):
    functions = [('uint8_t', 'jt808_days_in_month'), ('void', 'jt808_apply_timezone'),
                 ('uint16_t', 'encode_location_base'), ('uint16_t', 'encode_location_compact'),
                 ('uint16_t', 'clamp_voltage_units'), ('uint16_t', 'coordinate_extension_tail'),
                 ('uint16_t', 'altitude_extension_tail'), ('uint16_t', 'encode_location_online')]
    code = '\n'.join('static ' + kind + ' ' + function(source, name)
                     for kind, name in functions if name + '(' in source)
    for _, name in functions:
        code = re.sub(r'\b' + name + r'\b', prefix + name, code)
    return code


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', type=Path, required=True)
    args = parser.parse_args()
    code = r'''
#include "gps.h"
#include "jt808.h"
#include "flash_config.h"
#include "blind_zone.h"
#include <assert.h>
#include <math.h>
#include <string.h>
#include <stdio.h>
#define JT808_LOCATION_ONLINE_MAX 67U
static device_config_t config;
static uint32_t s_alarm_flags;
static bool physical_acc, logical_acc;
static float car, battery;
static int csq;
device_config_t *cfg_get(void) { return &config; }
bool hw_acc_is_on(void) { return physical_acc; }
bool jt808_get_logical_acc(void) { return logical_acc; }
float adc_get_car_voltage(void) { return car; }
float adc_get_bat_voltage(void) { return battery; }
int ec800m_get_csq(void) { return csq; }
'''
    code += encoder(args.baseline.read_text(encoding='utf-8'), 'old_')
    code += encoder((ROOT/'src/jt808.c').read_text(encoding='utf-8'), 'new_')
    code += r'''
int main(void) {
    gps_data_t g={0}; uint8_t old[80], current[80];
    uint32_t seed=0x73941652;
    for(unsigned i=0;i<20000;i++) {
        seed=seed*1664525U+1013904223U;
        g.lat=(double)(int32_t)seed/24000000.0;
        seed=seed*1664525U+1013904223U;
        g.lon=(double)(int32_t)seed/12000000.0;
        g.speed_kmh=(float)(i%65000)/10.0f;g.heading=(float)(i%360);
        g.altitude_m=(float)(i%60000);g.hdop=(float)(i%1200)/10.0f;
        g.fix_quality=i%9;g.satellites=i%100;
        g.year=2000+i%200;g.month=1+i%12;g.day=1+i%28;
        g.hour=i%24;g.minute=i%60;g.second=(i/3)%60;
        config.gmt_sign=(i%3)-1;config.gmt_hour=i%15;config.gmt_min=i%65;
        config.mileage_m=seed;s_alarm_flags=seed^0x173246;
        physical_acc=(i&1)!=0;logical_acc=(i&2)!=0;
        car=(float)(i%80000)/100.0f;battery=(float)(i%5000)/1000.0f;
        csq=i%100;
        memset(old,0xA5,sizeof old);memset(current,0xA5,sizeof current);
        assert(old_encode_location_compact(&g,old)==new_encode_location_compact(&g,current));
        assert(memcmp(old,current,34)==0);
        for(unsigned history=0;history<2;history++) {
            memset(old,0xA5,sizeof old);memset(current,0xA5,sizeof current);
            assert(old_encode_location_online(&g,old,seed,history)==
                   new_encode_location_online(&g,current,seed,history));
            assert(memcmp(old,current,sizeof old)==0);
        }
    }
    puts("PASS: 20000 compact + 40000 online/historical location bodies identical");
}
'''
    with tempfile.TemporaryDirectory() as tmp:
        d=Path(tmp)
        (d/'h.c').write_text(code,encoding='utf-8')
        subprocess.run([shutil.which('gcc'),'-std=c99','-O2','-Wall','-Wextra','-Werror',
                        '-I',str(ROOT/'include'),str(d/'h.c'),'-lm','-o',str(d/'h.exe')],check=True)
        subprocess.run([str(d/'h.exe')],check=True)


if __name__=='__main__':
    main()
