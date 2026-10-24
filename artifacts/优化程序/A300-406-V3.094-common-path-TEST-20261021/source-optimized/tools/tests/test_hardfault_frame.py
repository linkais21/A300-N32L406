"""Fault capture must not dereference a damaged exception stack."""
import re, shutil, subprocess, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def main():
    s=(ROOT/'src/main.c').read_text(encoding='utf-8')
    signature=re.search(r'void hardfault_capture\([^)]*\)\n\{',s)
    assert signature
    start=signature.start();end=s.index('\nvoid HardFault_Handler',start)
    capture=s[start:end].replace('0x20000000U','((uintptr_t)arena)').replace('0x20006000U','((uintptr_t)(arena+40))')
    call='hardfault_capture(p, exc)' if 'exc_return' in capture else 'hardfault_capture(p)'
    h=r"""
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <assert.h>
#include <setjmp.h>
static uint32_t arena[40],pc,lr;
static jmp_buf done;
static bool s_iwdg_started;
static struct {uint32_t CFSR,HFSR;} scb;
#define SCB (&scb)
static void reset_diag_record_fault(uint32_t p,uint32_t l,uint32_t c,uint32_t h){(void)c;(void)h;pc=p;lr=l;}
static void NVIC_SystemReset(void){longjmp(done,1);}
"""+capture+r"""
static void run(uint32_t *p,uint32_t exc,uint32_t wantpc,uint32_t wantlr){
    (void)exc;pc=lr=0xffffffffU;if(!setjmp(done)){CALL;}
    assert(pc==wantpc && lr==wantlr);
}
int main(void){
    arena[6]=0x12345678;arena[5]=0x87654321;
    run(arena,0xfffffff9U,arena[6],arena[5]);
    run(NULL,0xfffffff9U,0,0);
    run((uint32_t *)((uintptr_t)arena+1),0xfffffff9U,0,0);
    run(arena+33,0xfffffff9U,0,0);
    arena[18+6]=0x11223344;arena[18+5]=0x55667788;
    run(arena,0xffffffe9U,arena[24],arena[23]);
    run(arena+15,0xffffffe9U,0,0);
    SCB->CFSR=0x1000U;run(arena,0xfffffff9U,0,0);
    return 0;
}
"""
    h=h.replace('CALL',call)
    with tempfile.TemporaryDirectory(prefix='fault_frame_') as td:
        p=Path(td);(p/'h.c').write_text(h)
        subprocess.run([shutil.which('gcc') or 'clang','-std=c99','-O1','-Wall','-Wextra','-Werror',str(p/'h.c'),'-o',str(p/'h.exe')],check=True,timeout=60)
        subprocess.run([str(p/'h.exe')],check=True,timeout=10)
    print('fault capture: PASS')
if __name__=='__main__':main()
