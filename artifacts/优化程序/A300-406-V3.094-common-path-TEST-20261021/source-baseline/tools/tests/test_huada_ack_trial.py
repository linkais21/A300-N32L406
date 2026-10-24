"""Host acceptance of the isolated Huada ACK transaction (not wired to firmware)."""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
TRIAL = ROOT / 'tools/experiments/huada_ack'


def test_transaction():
    cc = shutil.which('gcc') or shutil.which('clang')
    assert cc, 'host C compiler required'
    with tempfile.TemporaryDirectory(prefix='huada_ack_') as directory:
        p = Path(directory)
        (p / 'test.c').write_text(r'''
#include <assert.h>
#include <string.h>
#include "huada_ack.h"
static unsigned sends;
static int fail;
static int tx(const uint8_t *p, uint16_t n) {
    assert(p && n >= 8 && n <= 468); ++sends; return fail ? -1 : 0;
}
static void checksum(uint8_t *p, unsigned n) {
    uint8_t a=0,b=0;
    for(unsigned i=2;i<n-2;i++){a+=p[i];b+=a;}
    p[n-2]=a;p[n-1]=b;
}
int main(void) {
    huada_ack_t s={0};
    uint8_t f[73]={0xf1,0xd9,0x0b,0x32,65,0};
    uint8_t ack[10]={0xf1,0xd9,5,1,2,0,0x0b,0x32,0,0};
    checksum(f,sizeof f);checksum(ack,sizeof ack);
    assert(huada_ack_start(&s,f,sizeof f,100,1000,tx));
    assert(s.state==HUADA_ACK_WAIT && sends==1);
    assert(!huada_ack_start(&s,f,sizeof f,101,1000,tx));
    huada_ack_poll(&s,199);assert(s.state==HUADA_ACK_WAIT && sends==1);
    huada_ack_receive(&s,ack,9,200);assert(s.state==HUADA_ACK_WAIT);
    ack[9]^=1;huada_ack_receive(&s,ack,10,200);assert(s.state==HUADA_ACK_WAIT);
    ack[9]^=1;ack[7]=0x33;checksum(ack,10);
    huada_ack_receive(&s,ack,10,200);assert(s.state==HUADA_ACK_WAIT);
    ack[7]=0x32;checksum(ack,10);
    huada_ack_receive(&s,ack,10,200);assert(s.state==HUADA_ACK_OK);
    huada_ack_receive(&s,ack,10,201);assert(s.state==HUADA_ACK_OK && sends==1);
    assert(huada_ack_start(&s,f,sizeof f,300,1000,tx));
    ack[3]=0;checksum(ack,10);huada_ack_receive(&s,ack,10,301);
    assert(s.state==HUADA_ACK_NAK);
    assert(huada_ack_start(&s,f,sizeof f,0xfffffff0u,32,tx));
    huada_ack_poll(&s,15);assert(s.state==HUADA_ACK_WAIT);
    huada_ack_poll(&s,16);assert(s.state==HUADA_ACK_TIMEOUT);
    ack[3]=1;checksum(ack,10);huada_ack_receive(&s,ack,10,17);
    assert(s.state==HUADA_ACK_TIMEOUT);
    assert(huada_ack_start(&s,f,sizeof f,500,10,tx));
    huada_ack_receive(&s,ack,10,510);assert(s.state==HUADA_ACK_TIMEOUT);
    assert(huada_ack_start(&s,f,sizeof f,600,10,tx));
    huada_ack_cancel(&s);huada_ack_cancel(&s);
    huada_ack_receive(&s,ack,10,601);assert(s.state==HUADA_ACK_CANCELLED);
    fail=1;assert(!huada_ack_start(&s,f,sizeof f,700,100,tx));
    assert(s.state==HUADA_ACK_TX_ERROR);fail=0;
    unsigned before=sends;
    assert(!huada_ack_start(&s,0,73,800,100,tx));
    assert(!huada_ack_start(&s,f,72,800,100,tx));
    assert(!huada_ack_start(&s,f,73,800,0,tx));
    assert(!huada_ack_start(&s,f,73,800,0x80000000u,tx));
    assert(!huada_ack_start(&s,f,73,800,100,0));
    f[72]^=1;assert(!huada_ack_start(&s,f,73,800,100,tx));f[72]^=1;
    f[2]=6;checksum(f,73);assert(!huada_ack_start(&s,f,73,800,100,tx));
    f[2]=0x0b;f[3]=0x10;checksum(f,73);
    assert(!huada_ack_start(&s,f,73,800,100,tx)); /* bad position length */
    f[3]=0x33;checksum(f,73);
    assert(!huada_ack_start(&s,f,73,800,100,tx)); /* bad BDS length */
    assert(sends==before);
    uint8_t bds[468]={0xf1,0xd9,0x0b,0x33,0xcc,1};
    checksum(bds,sizeof bds);
    assert(huada_ack_start(&s,bds,sizeof bds,900,100,tx));
    huada_ack_cancel(&s);
    uint8_t time[28]={0xf1,0xd9,0x0b,0x11,20,0};
    checksum(time,sizeof time);
    assert(huada_ack_start(&s,time,sizeof time,1000,100,tx));
    huada_ack_cancel(&s);
    uint8_t pos[25]={0xf1,0xd9,0x0b,0x10,17,0};
    checksum(pos,sizeof pos);
    assert(huada_ack_start(&s,pos,sizeof pos,1100,100,tx));
    huada_ack_cancel(&s);
    assert(!huada_ack_start(0,pos,sizeof pos,1200,100,tx));
    huada_ack_receive(0,0,0,0);huada_ack_poll(0,0);huada_ack_cancel(0);
    return 0;
}
''', encoding='ascii')
        exe = p / 'test.exe'
        subprocess.run([cc, '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-I', str(TRIAL), str(p / 'test.c'),
                        str(TRIAL / 'huada_ack.c'), '-o', str(exe)], check=True, timeout=60)
        subprocess.run([str(exe)], check=True, timeout=10)


if __name__ == '__main__':
    test_transaction()
    print('Huada ACK trial: PASS (matching, checksum, deadline, wrap, cancel, TX failure, bounds)')
