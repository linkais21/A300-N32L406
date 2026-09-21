"""Actual relay GPIO driver: bounded pulse even without main-loop service."""
from pathlib import Path
import subprocess
import tempfile
from test_f39_actions import find_compiler
ROOT=Path(__file__).resolve().parents[2]
HARNESS=r'''
#include <assert.h>
#include <stdint.h>
#include "relay.h"
static int output;
void GPIO_SetBits(void *p,unsigned pin){(void)p;(void)pin;output=1;}
void GPIO_ResetBits(void *p,unsigned pin){(void)p;(void)pin;output=0;}
uint32_t __get_PRIMASK(void){return 0;}
void __disable_irq(void){}
void __set_PRIMASK(uint32_t v){(void)v;}
int main(void){
 assert(!output);assert(relay_test_low());assert(output&&relay_get());
 for(int i=0;i<1500;i++)relay_test_tick();
 assert(relay_test_remaining()==1500);assert(!relay_test_low());
 relay_set(true);assert(relay_test_remaining()==1500);
 for(int i=0;i<1499;i++){relay_test_tick();}assert(output);
 relay_test_tick();assert(!output&&!relay_get()&&!relay_test_remaining());
 assert(relay_test_low());relay_test_high();assert(!output&&!relay_test_remaining());
 relay_test_high();assert(!output);assert(relay_test_low());relay_set(false);assert(!output&&!relay_test_remaining());
 relay_set(true);assert(!relay_test_low());relay_set(false);
 return 0;
}
'''
def main():
 with tempfile.TemporaryDirectory() as tmp:
  p=Path(tmp);(p/'h.c').write_text(HARNESS)
  (p/'n32l40x.h').write_text('#include <stdint.h>\n#define GPIOA ((void*)1)\n#define GPIO_PIN_11 2048U\nvoid GPIO_SetBits(void*,unsigned);\nvoid GPIO_ResetBits(void*,unsigned);\nuint32_t __get_PRIMASK(void);\nvoid __disable_irq(void);\nvoid __set_PRIMASK(uint32_t);\n')
  subprocess.run([find_compiler(),'-std=c99','-Wall','-Wextra','-Werror','-I',str(p),'-I',str(ROOT/'include'),str(p/'h.c'),str(ROOT/'src/relay.c'),'-o',str(p/'h.exe')],check=True)
  subprocess.run([str(p/'h.exe')],check=True)
 print('production relay PASS')
if __name__=='__main__':main()
