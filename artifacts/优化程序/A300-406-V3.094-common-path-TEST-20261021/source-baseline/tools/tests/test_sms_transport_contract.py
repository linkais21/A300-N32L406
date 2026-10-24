import os, pathlib, shutil, subprocess, tempfile
ROOT=pathlib.Path(__file__).resolve().parents[2]
def main():
    cc=shutil.which('gcc')
    if not cc:
        print('SKIP: gcc not found'); return
    src=r'''#include <assert.h>
#include <string.h>
#include "peripherals.h"
static int ready; static int calls;
int ec800m_sms_send(const char *p,const char *t){(void)p;(void)t;calls++; return ready?0:-2;}
int dbg_printf(const char *f,...){(void)f;return 0;}
void sms_ingress_feed_line(const char *l){(void)l;} void sms_ingress_process(void){}
void sms_ingress_set_callback(void *cb){(void)cb;}
void GPIO_ResetBits(void *p,unsigned x){(void)p;(void)x;}
int main(void){assert(sms_send("1","X")<0);ready=1;assert(sms_send("1","X")==0);assert(calls==2);return 0;}'''
    with tempfile.TemporaryDirectory() as d:
        c=pathlib.Path(d)/'t.c'; e=pathlib.Path(d)/'t.exe'; c.write_text(src)
        (pathlib.Path(d)/'n32l40x.h').write_text('#ifndef N32L40X_H\n#define N32L40X_H\n#define GPIOB ((void*)0)\n#define GPIO_PIN_12 12\nvoid GPIO_ResetBits(void*,unsigned);\n#endif\n')
        subprocess.run([cc,'-std=c99','-Wall','-Wextra','-Werror','-I',d,'-I',str(ROOT/'include'),str(c),str(ROOT/'src'/'peripherals.c'),'-o',str(e)],check=True)
        subprocess.run([str(e)],check=True)
    print('PASS')
if __name__=='__main__': main()
