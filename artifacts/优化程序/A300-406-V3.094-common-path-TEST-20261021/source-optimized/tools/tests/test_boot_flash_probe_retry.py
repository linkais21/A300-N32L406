"""Execute the production platform probe with transient and permanent failures."""
from pathlib import Path
import subprocess
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT/'bootloader/src/platform_n32l406.c').read_text(encoding='utf-8')
body = source[source.index('bool boot_ext_device_valid(void)'):source.index('bool boot_ext_read(')]
harness = r'''
#include <stdbool.h>
#include <stdint.h>
#include <assert.h>
static unsigned calls, waits, feeds, fail_count;
#define BOOT_FLASH_PROBE_ATTEMPTS 100U
static bool jedec_valid(void) { return ++calls > fail_count; }
void boot_flash_probe_wait(void) { ++waits; }
void boot_watchdog_feed(void) { ++feeds; }
'''+body+r'''
int main(void) {
    fail_count=3;
    assert(boot_ext_device_valid());
    assert(calls==4 && waits==3 && feeds>=3);
    calls=waits=feeds=0; fail_count=1000;
    assert(!boot_ext_device_valid());
    assert(calls==100 && waits==99);
    calls=waits=feeds=0; fail_count=0;
    assert(boot_ext_device_valid());
    assert(calls==1 && waits==0);
}
'''
with tempfile.TemporaryDirectory() as temp:
    p=Path(temp)
    (p/'test.c').write_text(harness,encoding='ascii')
    subprocess.run([shutil.which('gcc'),'-std=c99',str(p/'test.c'),'-o',str(p/'test.exe')],check=True)
    subprocess.run([str(p/'test.exe')],check=True)
print('boot Flash probe retry: PASS (transient, persistent, immediate)')
