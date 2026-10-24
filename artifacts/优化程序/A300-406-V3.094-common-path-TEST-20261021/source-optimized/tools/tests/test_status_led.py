"""Compile the production LED driver against GPIO observations."""
import subprocess
import tempfile
from pathlib import Path
from test_jt808_dual_session import compiler

ROOT = Path(__file__).resolve().parents[2]
HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include "status_led.h"
static int blue;
void GPIO_SetBits(void *port, unsigned pin) { assert(port==(void*)4 && pin==1U); blue=1; }
void GPIO_ResetBits(void *port, unsigned pin) { assert(port==(void*)4 && pin==1U); blue=0; }
int main(void) {
 status_led_process(false,false,0U); assert(blue);
 status_led_process(false,false,999U); assert(blue);
 status_led_process(false,false,1000U); assert(!blue);
 status_led_process(false,false,1999U); assert(!blue);
 status_led_process(false,false,2000U); assert(blue);
 status_led_process(false,true,2500U); assert(blue);
 status_led_process(false,true,3500U); assert(blue);
 status_led_process(true,true,3501U); assert(!blue);
 status_led_process(true,false,4000U); assert(!blue);
 status_led_process(false,false,4500U); assert(blue);
 status_led_process(false,false,5500U); assert(!blue);
 status_led_process(true,false,0xFFFFFE00U); assert(!blue);
 status_led_process(false,false,0xFFFFFE00U); assert(blue);
 status_led_process(false,false,488U); assert(!blue);
 status_led_process(false,true,489U); assert(blue);
 status_led_process(false,false,490U); assert(blue);
 status_led_process(false,false,1490U); assert(!blue);
 return 0;
}
'''

def main():
    with tempfile.TemporaryDirectory(prefix='status_led_') as directory:
        t=Path(directory)
        (t/'h.c').write_text(HARNESS, encoding='ascii')
        (t/'n32l40x.h').write_text('#define GPIOD ((void*)4)\n#define GPIO_PIN_0 1U\nvoid GPIO_SetBits(void*,unsigned);\nvoid GPIO_ResetBits(void*,unsigned);\n', encoding='ascii')
        subprocess.run([compiler(),'-std=c99','-Wall','-Wextra','-Werror','-I',str(t),'-I',str(ROOT/'include'),str(t/'h.c'),str(ROOT/'src/status_led.c'),'-o',str(t/'h.exe')],check=True)
        subprocess.run([str(t/'h.exe')],check=True)
    source=(ROOT/'src/main.c').read_text(encoding='utf-8')
    fn=source[source.index('void work_mode_process('):source.index('static void idle_sleep_process(')]
    assert fn.index('status_led_process(') < fn.index('case WORK_ACTION_ENTER_STOP1:')
    assert 'src/status_led.c' in (ROOT/'Makefile').read_text(encoding='utf-8')
    print('test_status_led: PASS')

if __name__ == '__main__':
    main()
