"""Exercise production wake routing for every flag combination and repeated calls."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    cc = os.environ.get('CC') or shutil.which('gcc')
    assert cc, 'host C compiler required'
    with tempfile.TemporaryDirectory(prefix='power_routing_') as tmp:
        d = Path(tmp)
        (d/'config.h').write_text('', encoding='ascii')
        (d/'n32l40x.h').write_text('''
#define RCC_APB2_PERIPH_AFIO 1
#define ENABLE 1
#define EXTI_LINE0 1u
#define EXTI_LINE2 4u
#define EXTI_LINE12 4096u
#define EXTI_LINE15 32768u
void RCC_EnableAPB2PeriphClk(unsigned, int);
int EXTI_GetITStatus(unsigned);
void EXTI_ClrITPendBit(unsigned);
''', encoding='ascii')
        (d/'h.c').write_text('''
#include <assert.h>
#include <stdio.h>
#include "power_mgr.h"
static unsigned calls[8], count, init_count, clocks;
void RCC_EnableAPB2PeriphClk(unsigned p, int e) { assert(p==1 && e==1); clocks++; }
int EXTI_GetITStatus(unsigned p) { (void)p; return 0; }
void EXTI_ClrITPendBit(unsigned p) { (void)p; }
void work_mode_sleep_init(void) { init_count++; }
void work_mode_sleep_isr_wake(work_sleep_wake_t s) { assert(count<8); calls[count++]=s; }
int main(void) {
    pwr_init(); assert(init_count==1 && clocks==1);
    for (unsigned mask=0; mask<128; mask++) {
        for (unsigned repeat=0; repeat<3; repeat++) {
            count=0; unsigned i=0;
            pwr_wake((wake_src_t)mask);
            if (mask & WAKE_SRC_ACC) assert(calls[i++]==WORK_SLEEP_WAKE_ACC);
            if (mask & WAKE_SRC_SOS) assert(calls[i++]==WORK_SLEEP_WAKE_SOS);
            if (mask & (WAKE_SRC_LIGHT|WAKE_SRC_CHARGE)) assert(calls[i++]==WORK_SLEEP_WAKE_POWER);
            assert(count==i);
        }
    }
    puts("PASS: 128 wake masks, three repeated calls each");
    return 0;
}
''', encoding='ascii')
        subprocess.run([cc, '-std=c99', '-Wall', '-Wextra', '-Werror', '-I', str(d),
                        '-I', str(ROOT/'include'), str(d/'h.c'),
                        str(ROOT/'src/power_mgr.c'), '-o', str(d/'h.exe')], check=True)
        subprocess.run([str(d/'h.exe')], check=True)


if __name__ == '__main__':
    main()
