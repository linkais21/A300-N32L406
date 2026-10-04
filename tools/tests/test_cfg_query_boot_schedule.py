"""Execute the production main-loop query gate with a simulated boot/clock."""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / 'src/main.c').read_text(encoding='utf-8')
assert 'bool cfg_query_started = false;' in source
assert 'service_config_query(&cfg_query_started);' in source
init = '    bool cfg_query_started = false;\n    bool *started = &cfg_query_started;'
start = source.index('    if (!*started &&', source.index('static void service_config_query(bool *started)\n{'))
gate = source[start:source.index('    reset_diag_mark_phase(RESET_DIAG_PHASE_CONFIG)', start)]
harness = r'''
#include <stdbool.h>
#include <stdint.h>
#include <assert.h>
static uint32_t now;
static bool ready, online, sleeping, ota, busy;
static unsigned starts;
static int start_result;
#define TICK_MS() now
static bool ec800m_is_ready(void) { return ready; }
static bool jt808_is_online(void) { return online; }
static bool work_mode_sleep_is_in_stop1(void) { return sleeping; }
static bool fota_is_active(void) { return ota; }
static bool cfg_query_is_busy(void) { return busy; }
static int cfg_query_start(void) { ++starts; return start_result; }
static void boot(void) {
INIT
    starts=0; ready=false; online=false; sleeping=false; ota=false; busy=false;
    for (unsigned step=0; step<12; ++step) {
        now=step*60001U;
        if(step==1) ready=true;
        if(step==2) { online=true; sleeping=true; }
        if(step==3) { sleeping=false; ota=true; }
        if(step==4) { ota=false; busy=true; }
        if(step==5) { busy=false; start_result=-1; }
        if(step==6) start_result=0;
        if(step==8) online=false;
        if(step==9) online=true;
        if(step==10) now=UINT32_MAX;
        if(step==11) now=0;
GATE
        assert(starts == (step<5 ? 0U : step==5 ? 1U : 2U));
    }
}
int main(void) { boot(); boot(); return 0; }
'''.replace('INIT', init).replace('GATE', gate)
with tempfile.TemporaryDirectory(prefix='cfg_boot_') as tmp:
    path = Path(tmp)
    (path / 'test.c').write_text(harness, encoding='utf-8')
    cc = shutil.which('gcc')
    assert cc, 'host gcc required'
    subprocess.run([cc, '-std=c99', '-Wall', '-Wextra', '-Werror',
                    '-Wno-unused-but-set-variable', str(path / 'test.c'),
                    '-o', str(path / 'test.exe')], check=True)
    subprocess.run([str(path / 'test.exe')], check=True)
print('cfg query boot schedule: PASS')
