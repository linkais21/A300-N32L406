"""Boot UART logging cannot block installation when TX flags stall."""
from pathlib import Path
import shutil,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[2]
HEADER=r'''
#include <stdint.h>
typedef struct {unsigned Pin,GPIO_Mode,GPIO_Alternate,GPIO_Current,GPIO_Slew_Rate,GPIO_Pull;} GPIO_InitType;
typedef struct {unsigned BaudRate,Mode;} USART_InitType;
#define USART1 1
#define GPIOA 1
#define RESET 0
#define ENABLE 1
#define USART_FLAG_TXDE 1
#define USART_FLAG_TXC 2
#define RCC_APB2_PERIPH_GPIOA 1
#define RCC_APB2_PERIPH_USART1 2
#define GPIO_PIN_9 512
#define GPIO_Mode_AF_PP 1
#define GPIO_AF4_USART1 4
#define GPIO_DC_4mA 4
#define GPIO_Slew_Rate_High 1
#define GPIO_No_Pull 0
#define USART_MODE_TX 1
int USART_GetFlagStatus(int,unsigned);
void USART_SendData(int,uint8_t);
void RCC_EnableAPB2PeriphClk(unsigned,int);
void GPIO_InitStruct(GPIO_InitType*);
void GPIO_InitPeripheral(int,GPIO_InitType*);
void USART_StructInit(USART_InitType*);
void USART_Init(int,USART_InitType*);
void USART_Enable(int,int);
'''
HARNESS=r'''
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "n32l40x.h"
#include "image_install.h"
static char output[256];static unsigned count,polls,feeds;static int mode;
int USART_GetFlagStatus(int u,unsigned f){(void)u;++polls;return mode==1?0:(mode==2&&f==USART_FLAG_TXC?0:1);}
void USART_SendData(int u,uint8_t c){(void)u;assert(count+1<sizeof output);output[count++]=c;}
void boot_watchdog_feed(void){++feeds;assert(feeds<=64000);}
void RCC_EnableAPB2PeriphClk(unsigned p,int e){(void)p;(void)e;}
void GPIO_InitStruct(GPIO_InitType *g){memset(g,0,sizeof *g);}
void GPIO_InitPeripheral(int p,GPIO_InitType *g){(void)p;assert(g->Pin==512&&g->GPIO_Alternate==4);}
void USART_StructInit(USART_InitType *u){memset(u,0,sizeof *u);}
void USART_Init(int p,USART_InitType *u){(void)p;assert(u->BaudRate==115200);}
void USART_Enable(int p,int e){(void)p;(void)e;}
int main(int argc,char **argv){(void)argc;mode=atoi(argv[1]);
 boot_install_progress(50,100,false);
 if(!mode){assert(!strcmp(output,"[FOTA] install progress=50% bytes=50/100 state=writing\r\n"));count=0;memset(output,0,sizeof output);boot_install_progress(100,100,true);assert(strstr(output,"100% bytes=100/100 state=trial-ready"));}
 else {assert(feeds==64000);unsigned old=polls;boot_install_progress(100,100,true);assert(polls==old);}
 return 0;
}
'''
def main():
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp);(p/'n32l40x.h').write_text(HEADER)
        for n in ['n32l40x_usart.h','n32l40x_gpio.h','n32l40x_rcc.h']:(p/n).write_text('')
        (p/'h.c').write_text(HARNESS)
        subprocess.run([shutil.which('gcc') or shutil.which('clang'),'-std=c99','-Wall','-Wextra','-Werror',
                        '-I',str(p),'-I',str(ROOT/'bootloader/include'),'-I',str(ROOT/'include'),
                        str(p/'h.c'),str(ROOT/'bootloader/src/boot_progress.c'),'-o',str(p/'h.exe')],check=True)
        for mode in ['0','1','2']:subprocess.run([str(p/'h.exe'),mode],check=True)
    print('boot progress UART PASS (output, TXDE timeout, TXC timeout)')
if __name__=='__main__':main()
