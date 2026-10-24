"""Real TIM9 calibration code under bounded register/peripheral simulation."""
from pathlib import Path
import subprocess,tempfile
import test_blind_zone_replay as host
ROOT=Path(__file__).resolve().parents[2]
HEADER=r'''
#pragma once
#include <stdint.h>
#include <stdbool.h>
typedef struct {uint32_t CTRL1,STS,CCMOD2,CCEN;} TIM_Module;
extern TIM_Module timer;
typedef struct {uint32_t CFG;} RCC_Module;
extern RCC_Module clock_register;
extern uint32_t SystemCoreClock;
#define RCC (&clock_register)
#define RCC_CFG_APB1PRES 0x700U
#define TIM9 (&timer)
#define TIM_CTRL1_C3SEL 0x2000U
#define ENABLE 1
#define DISABLE 0
#define RESET 0
#define RCC_APB1_PERIPH_TIM9 512U
#define TIM_PSC_RELOAD_MODE_IMMEDIATE 1
#define TIM_CH_3 3
#define TIM_IC_POLARITY_RISING 0
#define TIM_IC_SELECTION_DIRECTTI 1
#define TIM_IC_PSC_DIV8 12
#define TIM_CCMOD2_CC3SEL_0 1U
#define TIM_CCEN_CC3EN 256U
#define TIM_FLAG_CC3 8
#define TIM_FLAG_CC3OF 2048
#define TIM_INT_CC3 8
typedef struct {unsigned Channel,IcPolarity,IcSelection,IcPrescaler,IcFilter;} TIM_ICInitType;
typedef struct {uint32_t HclkFreq,Pclk1Freq;} RCC_ClocksType;
extern uint32_t tick;
#define TICK_MS() tick
void RCC_EnableAPB1PeriphClk(unsigned,int);
void RCC_GetClocksFreqValue(RCC_ClocksType*);
void TIM_DeInit(TIM_Module*);
void TIM_ConfigPrescaler(TIM_Module*,unsigned,unsigned);
void TIM_ICInit(TIM_Module*,TIM_ICInitType*);
void TIM_Enable(TIM_Module*,int);
int TIM_GetFlagStatus(TIM_Module*,unsigned);
uint16_t TIM_GetCap3(TIM_Module*);
void TIM_ClrIntPendingBit(TIM_Module*,unsigned);
'''
HARNESS=r'''
#include <assert.h>
#include "rtc_lsi_calibration.h"
#include "n32l40x.h"
TIM_Module timer;
RCC_Module clock_register={0x500U};
uint32_t SystemCoreClock=64000000U;
uint32_t tick;
static unsigned clocked,running,mode,reads,divider;
static uint16_t counter;
void RCC_EnableAPB1PeriphClk(unsigned c,int en){assert(c==512);clocked=en;}
void RCC_GetClocksFreqValue(RCC_ClocksType *c){c->HclkFreq=64000000;c->Pclk1Freq=16000000;}
void TIM_DeInit(TIM_Module *t){t->CTRL1=0;t->STS=0;running=0;}
void TIM_ConfigPrescaler(TIM_Module*t,unsigned p,unsigned m){(void)t;(void)m;divider=p;}
void TIM_ICInit(TIM_Module*t,TIM_ICInitType*c){(void)t;assert(c->Channel==3 && c->IcPrescaler==3 && !c->IcFilter);}
void TIM_Enable(TIM_Module*t,int en){if(en)assert(t->CCMOD2==13 && t->CCEN==256 && (t->CTRL1&TIM_CTRL1_C3SEL));running=en;}
int TIM_GetFlagStatus(TIM_Module*t,unsigned f){
 (void)t; if(f==TIM_FLAG_CC3OF)return mode==2;
 ++reads; if(mode==4)return 0; if(mode==1){++tick;return 0;}
 return 1;
}
uint16_t TIM_GetCap3(TIM_Module*t){(void)t;counter=(uint16_t)(counter+(mode==3?1:187));return counter;}
void TIM_ClrIntPendingBit(TIM_Module*t,unsigned f){(void)t;(void)f;}
int main(void){
 counter=65000; /* capture wraps while averaging */
 uint32_t hz=rtc_lsi_measure_hz();
 assert(hz>=42779 && hz<=42782 && divider==31);
 assert(!running && !clocked);
 mode=1;reads=0;tick=UINT32_MAX-10;
 assert(rtc_lsi_measure_hz()==0 && reads<=51 && !running && !clocked);
 mode=2;reads=0;
 assert(rtc_lsi_measure_hz()==0 && !running && !clocked);
 mode=3;reads=0;
 assert(rtc_lsi_measure_hz()==0 && !running && !clocked);
 mode=4;reads=0; /* even a frozen SysTick cannot create an unbounded wait */
 assert(rtc_lsi_measure_hz()==0 && reads==200000 && !running && !clocked);
 mode=0;reads=0;SystemCoreClock=1234567U;
 assert(rtc_lsi_measure_hz()==0 && reads==0 && !running && !clocked);
 SystemCoreClock=64000000U;clock_register.CFG=0;
 assert(rtc_lsi_measure_hz()>42000 && divider==63 && !running && !clocked);
 return 0;
}
'''
with tempfile.TemporaryDirectory() as td:
 p=Path(td)
 for name in ['n32l40x.h','n32l40x_tim.h','n32l40x_rcc.h','config.h']:
  (p/name).write_text(HEADER if name=='n32l40x.h' else '#include "n32l40x.h"\n',encoding='ascii')
 (p/'h.c').write_text(HARNESS,encoding='ascii')
 subprocess.run([host.compiler(),'-std=c99','-Wall','-Wextra','-Werror','-I',str(p),'-I',str(ROOT/'include'),str(p/'h.c'),str(ROOT/'src/rtc_lsi_calibration.c'),'-o',str(p/'h.exe')],check=True)
 subprocess.run([str(p/'h.exe')],check=True)
print('RTC LSI averaging/wrap/timeout/invalid capture/cleanup: PASS')
