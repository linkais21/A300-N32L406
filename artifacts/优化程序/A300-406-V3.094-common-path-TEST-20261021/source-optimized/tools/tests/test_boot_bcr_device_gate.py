"""Missing NOR identity must not make all-FF bus reads look like erased BCR."""
from pathlib import Path
import shutil,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[2]
src=(ROOT/'bootloader/src/platform_n32l406.c').read_text(encoding='utf-8')
body=src[src.index('bool boot_bcr_read('):src.index('bool boot_bcr_write(')]
h=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
static bool identity,read_ok=true;static unsigned reads;
static bool jedec_valid(void){return identity;}
static bool boot_ext_read(uint32_t a,void*d,uint32_t n){(void)a;++reads;memset(d,0xff,n);return read_ok;}
'''+body+r'''
int main(void){uint8_t b[40];memset(b,0x5a,sizeof b);
 assert(!boot_bcr_read(0x100000,b,sizeof b));assert(!reads&&b[0]==0x5a);
 identity=true;assert(boot_bcr_read(0x100000,b,sizeof b));assert(reads==1&&b[0]==0xff);
 read_ok=false;assert(!boot_bcr_read(0x101000,b,sizeof b));
}
'''
with tempfile.TemporaryDirectory() as t:
 p=Path(t);(p/'h.c').write_text(h,encoding='utf-8')
 subprocess.run([shutil.which('gcc'),'-std=c99','-Wall','-Wextra','-Werror',str(p/'h.c'),'-o',str(p/'h.exe')],check=True)
 subprocess.run([str(p/'h.exe')],check=True)
print('boot BCR device gate: PASS (missing ID, erased data, I/O failure)')
