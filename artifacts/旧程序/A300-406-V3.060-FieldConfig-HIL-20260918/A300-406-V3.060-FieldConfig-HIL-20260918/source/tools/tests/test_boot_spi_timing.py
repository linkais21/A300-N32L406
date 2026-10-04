"""Execute production SPI helpers with delayed BSY and stuck peripheral flags."""
from pathlib import Path
import shutil
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[2]

HEADER=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#define GPIOA 1
#define GPIO_PIN_4 16
#define SPI1 1
#define RESET 0
#define SPI_I2S_TE_FLAG 1
#define SPI_I2S_RNE_FLAG 2
#define SPI_I2S_BUSY_FLAG 3
#define EXT_TIMEOUT_LOOPS 32U
#define SystemCoreClock 64000000U
static unsigned ticks,fall_tick,rise_tick,last_clock,txs,feeds,busy_reads;
static bool selected;
static unsigned mode;
static void __NOP(void) { ++ticks; }
static void boot_watchdog_feed(void) { assert(++feeds <= 200U); }
static void GPIO_SetBits(int p,int pin) {
 (void)p;(void)pin;
 if(selected) assert(ticks>last_clock);
 selected=false;rise_tick=ticks;
}
static void GPIO_ResetBits(int p,int pin) {
 (void)p;(void)pin; assert(ticks>rise_tick);selected=true;fall_tick=ticks;
}
static int SPI_I2S_GetStatus(int p,int flag) {
 (void)p;
 if(flag==SPI_I2S_TE_FLAG)return mode==1?0:1;
 if(flag==SPI_I2S_RNE_FLAG)return mode==2?0:1;
 ++busy_reads;
 if(mode==3)return 1;
 if(busy_reads<=3U) {++ticks;last_clock=ticks;return 1;}
 return 0;
}
static void SPI_I2S_TransmitData(int p,uint16_t b) {
 (void)p;(void)b;assert(selected && ticks>fall_tick);++txs;
}
static uint16_t SPI_I2S_ReceiveData(int p) {(void)p;return 0x68;}
'''
MAIN=r'''
int main(int argc,char**argv) {
 assert(argc==2);mode=strtoul(argv[1],0,10);
 cs_high();cs_low();uint8_t value=0;
 bool ok=spi_xfer(0x9f,&value);cs_high();
 if(mode==0){assert(ok&&value==0x68&&busy_reads>=4&&txs==1);}
 else {assert(!ok);assert(feeds<=200U);}
 cs_low();cs_high();assert(!selected);
 return 0;
}
'''

def main():
    src=(ROOT/'bootloader/src/platform_n32l406.c').read_text(encoding='utf-8')
    # This contiguous block must include the production CS timing helper.
    begin=src.index('static void cs_')
    code=src[begin:src.index('static bool read_status')]
    with tempfile.TemporaryDirectory() as directory:
        p=Path(directory);(p/'h.c').write_text(HEADER+code+MAIN,encoding='utf-8')
        subprocess.run([shutil.which('gcc'),'-std=c99','-Wall','-Wextra',
                        str(p/'h.c'),'-o',str(p/'h.exe')],check=True)
        for mode in range(4):subprocess.run([str(p/'h.exe'),str(mode)],check=True)
    print('boot SPI timing PASS (CS setup/hold/gap, BSY, TE/RNE/BSY timeouts)')

if __name__=='__main__':main()
