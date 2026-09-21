"""Actual relay GPIO driver: bounded pulse even without main-loop service."""
from pathlib import Path
import subprocess
import tempfile
from test_f39_actions import find_compiler
ROOT=Path(__file__).resolve().parents[2]
HARNESS=r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include "n32l40x.h"
#include "relay.h"
static int output;
static int clock_on, mode_ok, latch;
int dbg_printf(const char *fmt,...){(void)fmt;return 0;}
void RCC_EnableAPB2PeriphClk(unsigned mask,int en){assert(mask==RCC_APB2_PERIPH_GPIOA&&en);clock_on=1;}
void GPIO_InitStruct(GPIO_InitType *g){memset(g,0,sizeof *g);}
void GPIO_InitPeripheral(void *p,GPIO_InitType *g){(void)p;assert(clock_on&&g->Pin==2048U&&g->GPIO_Mode==GPIO_Mode_Out_PP);mode_ok=1;output=latch;}
int GPIO_ReadOutputDataBit(void *p,unsigned pin){(void)p;(void)pin;return latch;}
int GPIO_ReadInputDataBit(void *p,unsigned pin){(void)p;(void)pin;return output;}
void GPIO_SetBits(void *p,unsigned pin){(void)p;(void)pin;latch=1;if(clock_on&&mode_ok)output=1;}
void GPIO_ResetBits(void *p,unsigned pin){(void)p;(void)pin;latch=0;if(clock_on&&mode_ok)output=0;}
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
 clock_on=mode_ok=0;relay_set(true);assert(output&&relay_get());assert(!relay_test_low());
 mode_ok=0;relay_set(false);assert(!output&&!relay_get());
 return 0;
}
'''
def main():
 with tempfile.TemporaryDirectory() as tmp:
  p=Path(tmp);(p/'h.c').write_text(HARNESS)
  (p/'n32l40x.h').write_text('#include <stdint.h>\n#define GPIOA ((void*)1)\n#define GPIO_PIN_11 2048U\nvoid GPIO_SetBits(void*,unsigned);\nvoid GPIO_ResetBits(void*,unsigned);\nuint32_t __get_PRIMASK(void);\nvoid __disable_irq(void);\nvoid __set_PRIMASK(uint32_t);\n')
  with (p/'n32l40x.h').open('a') as f:
   f.write('typedef struct {unsigned Pin,GPIO_Mode,GPIO_Slew_Rate,GPIO_Current,GPIO_Pull;} GPIO_InitType;\n#define RCC_APB2_PERIPH_GPIOA 1U\n#define ENABLE 1\n#define GPIO_Mode_Out_PP 1U\n#define GPIO_Slew_Rate_High 1U\n#define GPIO_DC_12mA 12U\n#define GPIO_No_Pull 0U\nvoid RCC_EnableAPB2PeriphClk(unsigned,int);\nvoid GPIO_InitStruct(GPIO_InitType*);\nvoid GPIO_InitPeripheral(void*,GPIO_InitType*);\nint GPIO_ReadOutputDataBit(void*,unsigned);\nint GPIO_ReadInputDataBit(void*,unsigned);\n')
  (p/'n32l40x.h').write_text('#pragma once\n'+(p/'n32l40x.h').read_text())
  subprocess.run([find_compiler(),'-std=c99','-Wall','-Wextra','-Werror','-I',str(p),'-I',str(ROOT/'include'),str(p/'h.c'),str(ROOT/'src/relay.c'),'-o',str(p/'h.exe')],check=True)
  subprocess.run([str(p/'h.exe')],check=True)
 print('production relay PASS')
if __name__=='__main__':main()
