"""Real AGNSS scheduler yields to every active OTA phase."""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]

def test_ota_lockout_and_retry_deadline():
    cc = shutil.which("gcc") or shutil.which("clang")
    assert cc, "host compiler required"
    with tempfile.TemporaryDirectory(prefix="agnss_scheduler_") as directory:
        temp = Path(directory)
        (temp / "config.h").write_text('#include <stdint.h>\nextern uint32_t tick;\n#define TICK_MS() tick\n', encoding="ascii")
        (temp / "harness.c").write_text(r'''
#include <assert.h>
#include "agnss_manager.h"
#include "agnss_vendor.h"
#include "fota.h"
uint32_t tick;
static fota_state_t state;
static unsigned storage_calls;
fota_state_t fota_get_state(void){return state;}
bool ec800m_is_ready(void){return true;}
bool gps_is_valid(void){return false;}
void gnss_vendor_set_type(gnss_type_t t){(void)t;}
bool gnss_vendor_inject(gnss_type_t t,const uint8_t *p,uint16_t n){(void)t;(void)p;(void)n;return true;}
bool agnss_storage_init(void){return true;}
bool agnss_storage_get_latest(agnss_meta_t *m){(void)m;++storage_calls;return false;}
bool agnss_storage_read(uint32_t o,void *p,uint16_t n){(void)o;(void)p;(void)n;return false;}
uint8_t *agnss_storage_scratch(uint16_t *capacity){static uint8_t buf[32];*capacity=sizeof buf;return buf;}
int main(void){
    const fota_state_t active[]={FOTA_STATE_CONNECTING,FOTA_STATE_DOWNLOADING,FOTA_STATE_VERIFYING,FOTA_STATE_READY,FOTA_STATE_CHECK_CONNECTING,FOTA_STATE_CHECKING,FOTA_STATE_PREPARING};
    agnss_init(GNSS_TYPE_TAU804M);
    for(unsigned i=0;i<sizeof active/sizeof active[0];i++){state=active[i];agnss_process();assert(storage_calls==0);}
    state=FOTA_STATE_IDLE;agnss_process();assert(storage_calls==1);
    tick=59999;agnss_process();assert(storage_calls==1);tick=60000;agnss_process();assert(storage_calls==2);
    return 0;
}
''', encoding="ascii")
        exe = temp / "scheduler.exe"
        built = subprocess.run([cc, "-std=c99", "-Wall", "-Wextra", "-Werror", "-I", str(temp), "-I", str(ROOT / "include"), str(ROOT / "src/agnss_manager.c"), str(temp / "harness.c"), "-o", str(exe)], capture_output=True, text=True)
        assert built.returncode == 0, built.stderr
        run = subprocess.run([str(exe)], capture_output=True, text=True)
        assert run.returncode == 0, run.stderr

if __name__ == "__main__":
    test_ota_lockout_and_retry_deadline(); print("test_agnss_scheduler: PASS")
