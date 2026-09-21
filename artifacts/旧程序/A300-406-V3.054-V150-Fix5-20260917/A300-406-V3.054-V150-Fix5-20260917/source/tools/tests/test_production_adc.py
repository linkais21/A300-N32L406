"""ADC zero, timeout, recovery and stale-data semantics using the real driver."""
import tempfile
import subprocess
from pathlib import Path
from test_f39_actions import find_compiler
ROOT=Path(__file__).resolve().parents[2]
HEADERS={
 'config.h':'#include <stdint.h>\nextern volatile uint32_t g_tick_ms;\n#define TICK_MS() g_tick_ms\n#define ADC_CAR_CH 4\n#define ADC_BAT_CH 2\n#define ADC_CAR_RATIO 33.2f\n#define ADC_BAT_RATIO 2.0f\n',
 'hw_init.h':'', 'jt808.h':'#define ALM_POWER_CUT 1\n#define ALM_POWER_LOW 2\nvoid jt808_trigger_alarm(unsigned);\n',
 'mileage.h':'#include <stdint.h>\nint mileage_force_save(uint32_t);\n',
 'n32l40x.h':'#include <stdint.h>\n#define ADC 0\n#define ADC_SAMP_TIME_55CYCLES5 0\n#define ENABLE 1\n#define ADC_FLAG_ENDC 0\nvoid ADC_ConfigRegularChannel(int,int,int,int);\nvoid ADC_EnableSoftwareStartConv(int,int);\nint ADC_GetFlagStatus(int,int);\nuint16_t ADC_GetDat(int);\nvoid ADC_ClearFlag(int,int);\n',
}
HARNESS=r'''
#include <assert.h>
#include <stdint.h>
#include "adc_monitor.h"
volatile uint32_t g_tick_ms;
static unsigned raw=2500,alarms,channel,fail_channel;
void ADC_ConfigRegularChannel(int a,int c,int n,int s){(void)a;(void)n;(void)s;channel=(unsigned)c;}
void ADC_EnableSoftwareStartConv(int a,int b){(void)a;(void)b;}
int ADC_GetFlagStatus(int a,int b){(void)a;(void)b;++g_tick_ms;return channel!=fail_channel;}
uint16_t ADC_GetDat(int a){(void)a;return (uint16_t)raw;}
void ADC_ClearFlag(int a,int b){(void)a;(void)b;}
void jt808_trigger_alarm(unsigned a){(void)a;++alarms;}
int mileage_force_save(uint32_t t){(void)t;return 0;}
int main(void){
 adc_monitor_init();assert(!adc_monitor_valid());
 g_tick_ms=1000;adc_monitor_process();assert(adc_monitor_valid()&&adc_get_car_voltage()>20);
 fail_channel=4;g_tick_ms+=1000;adc_monitor_process();assert(!adc_monitor_valid()&&!alarms);
 fail_channel=2;g_tick_ms+=1000;adc_monitor_process();assert(!adc_monitor_valid()&&!alarms);
 fail_channel=0;raw=0;g_tick_ms+=1000;adc_monitor_process();assert(adc_monitor_valid()&&adc_get_car_voltage()==0);
 g_tick_ms+=2001;assert(!adc_monitor_valid());
 adc_monitor_init();assert(!adc_monitor_valid());
 return 0;
}
'''
def main():
 with tempfile.TemporaryDirectory() as tmp:
  p=Path(tmp)
  for name,body in HEADERS.items(): (p/name).write_text(body)
  (p/'h.c').write_text(HARNESS)
  subprocess.run([find_compiler(),'-std=c99','-Wall','-Wextra','-Werror','-I',str(p),'-I',str(ROOT/'include'),str(p/'h.c'),str(ROOT/'src/adc_monitor.c'),'-o',str(p/'h.exe')],check=True)
  subprocess.run([str(p/'h.exe')],check=True)
 print('production ADC PASS')
if __name__=='__main__':main()
