"""Exercise actual sleep-inclusive clock across tick wrap and partial seconds."""
from pathlib import Path
import subprocess, tempfile
import test_blind_zone_replay as host
root=Path(__file__).resolve().parents[2]
s=(root/'src/work_mode_sleep.c').read_text(encoding='utf-8')
s=s[s.index('uint32_t work_mode_sleep_monotonic_s(void)'):]
s=s[:s.index('\n}')+2]
h=r'''
#include <stdint.h>
#include <assert.h>
static uint32_t tick;
#define TICK_MS() tick
static volatile uint32_t s_elapsed_seconds;
static uint32_t s_awake_anchor_ms;
#define s_sleep_seconds s_elapsed_seconds
'''
m=r'''
int main(void){
 (void)s_awake_anchor_ms;
 tick=999; assert(work_mode_sleep_monotonic_s()==0);
 tick=1001; assert(work_mode_sleep_monotonic_s()==1);
 s_elapsed_seconds+=15; assert(work_mode_sleep_monotonic_s()==16);
 tick=2000; assert(work_mode_sleep_monotonic_s()==17);
 tick=UINT32_MAX-500; uint32_t before=work_mode_sleep_monotonic_s();
 tick=800; assert(work_mode_sleep_monotonic_s()==before+2);
 s_elapsed_seconds+=300; assert(work_mode_sleep_monotonic_s()==before+302);
 tick=1704; assert(work_mode_sleep_monotonic_s()==before+303);
 return 0;
}
'''
with tempfile.TemporaryDirectory() as td:
 p=Path(td); (p/'h.c').write_text(h+s+m,encoding='ascii')
 subprocess.run([host.compiler(),'-std=c99','-Wall','-Wextra','-Werror',str(p/'h.c'),'-o',str(p/'h.exe')],check=True)
 subprocess.run([str(p/'h.exe')],check=True)
print('sleep-inclusive monotonic tick wrap/fraction: PASS')
