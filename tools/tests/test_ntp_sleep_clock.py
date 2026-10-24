"""Compile the actual main-loop NTP scheduler with frozen awake tick."""
from pathlib import Path
import subprocess, tempfile
import test_blind_zone_replay as host
ROOT=Path(__file__).resolve().parents[2]
s=(ROOT/'src/main.c').read_text(encoding='utf-8')
s=s[s.index('#define NTP_RESYNC_INTERVAL'):s.index('\n\n',s.index('\n}',s.index('static void ntp_resync_process')))+2]
h=r'''
#include <stdint.h>
#include <stdbool.h>
#include <assert.h>
typedef struct { unsigned year, month, day, hour, minute, second; bool valid; } ec800m_time_t;
static uint32_t awake, elapsed;
static unsigned calls;
static bool ready=true, success=true;
#define TICK_MS() awake
static __attribute__((unused)) uint32_t work_mode_sleep_monotonic_s(void){return elapsed;}
static bool ec800m_is_ready(void){return ready;}
static bool ec800m_ntp_sync(ec800m_time_t *t){++calls;t->valid=success;return success;}
static void gps_apply_ntp_utc(unsigned y,unsigned m,unsigned d,unsigned h,unsigned n,unsigned s){(void)y;(void)m;(void)d;(void)h;(void)n;(void)s;}
static int dbg_printf(const char *fmt,...){(void)fmt;return 0;}
'''
m=r'''
int main(void){
 (void)awake; ntp_resync_process(); assert(calls==1);
 elapsed=21600; ntp_resync_process(); assert(calls==2);
 elapsed+=1; ntp_resync_process(); assert(calls==2);
 ready=false; elapsed+=21600; ntp_resync_process(); assert(calls==2);
 ready=true; success=false; ntp_resync_process(); assert(calls==3);
 elapsed+=299; ntp_resync_process(); assert(calls==3);
 elapsed+=1; success=true; ntp_resync_process(); assert(calls==4);
 elapsed+=21600; ntp_resync_process(); assert(calls==5);
 return 0;
}
'''
with tempfile.TemporaryDirectory() as td:
 p=Path(td); (p/'h.c').write_text(h+s+m,encoding='utf-8')
 subprocess.run([host.compiler(),'-std=c99','-Wall','-Wextra','-Werror',str(p/'h.c'),'-o',str(p/'h.exe')],check=True)
 subprocess.run([str(p/'h.exe')],check=True)
print('sleep-inclusive NTP cadence/retry: PASS')
