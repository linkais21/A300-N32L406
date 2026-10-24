"""Real UART formatter output and return count, including deployed quirks."""
from pathlib import Path
import shutil
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[2]

def main():
    with tempfile.TemporaryDirectory(prefix='dbg_format_') as td:
        p=Path(td)
        (p/'config.h').write_text('#define DBG_UART 1\n',encoding='ascii')
        (p/'n32l40x.h').write_text('#include <stdint.h>\n#define USART_FLAG_TXDE 1\n#define RESET 0\nint USART_GetFlagStatus(int,int);void USART_SendData(int,uint8_t);\n',encoding='ascii')
        (p/'test.c').write_text(r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <limits.h>
#include "debug_uart.h"
static char out[256];static unsigned pos;
int USART_GetFlagStatus(int a,int b){(void)a;(void)b;return 1;}
void USART_SendData(int a,uint8_t c){(void)a;assert(pos+1<sizeof out);out[pos++]=c;out[pos]=0;}
int main(void){
    const unsigned values[]={0,1,9,10,15,16,255,UINT_MAX};char ref[256];
    for(unsigned i=0;i<sizeof values/sizeof values[0];i++){
        pos=0;unsigned v=values[i];int n=dbg_printf("%u %08u %x %08x %8u",v,v,v,v,v);
        int m=snprintf(ref,sizeof ref,"%u %08u %x %08x %8u",v,v,v,v,v);
        assert(n==m&&!strcmp(out,ref));
    }
    const int signed_values[]={0,-1,INT_MIN,INT_MAX};
    for(unsigned i=0;i<4;i++){pos=0;int n=dbg_printf("%d",signed_values[i]);int m=snprintf(ref,sizeof ref,"%d",signed_values[i]);assert(n==m&&!strcmp(out,ref));}
    pos=0;int n=dbg_printf("%X|%s|%c|%%|%.2f|%f",0xabcU,(char*)0,'Z',1.25,-0.5);
    assert(!strcmp(out,"abc|(null)|Z|%|1.25|-0.500000")&&n==(int)strlen(out));
    /* All uint32 decimal/hex widths, including wider padding, plus samples
     * across the whole unsigned range. Keep the deployed lowercase %X. */
    unsigned random=0x12345678U;
    for(unsigned i=0;i<1024U;++i){
        random=random*1664525U+1013904223U;
        pos=0;
        n=dbg_printf("%u|%010u|%12u|%08x|%12x",random,random,random,random,random);
        int m=snprintf(ref,sizeof ref,"%u|%010u|%12u|%08x|%12x",random,random,random,random,random);
        assert(n==m&&!strcmp(out,ref));
    }
    pos=0;n=dbg_printf("%.0f|%.3f|%u",1234567890.0,0.125,UINT_MAX);
    assert(!strcmp(out,"1234567890|0.125|4294967295")&&n==(int)strlen(out));
    return 0;
}
''',encoding='ascii')
        exe=p/'test.exe'
        cc=shutil.which('gcc') or shutil.which('clang')
        subprocess.run([cc,'-std=c99','-O2','-Wall','-Wextra','-Werror','-I',str(p),'-I',str(ROOT/'include'),str(p/'test.c'),str(ROOT/'src/debug_uart.c'),'-o',str(exe)],check=True,timeout=60)
        subprocess.run([str(exe)],check=True,timeout=10)
    print('debug formatter output/count: PASS')
if __name__=='__main__':main()
