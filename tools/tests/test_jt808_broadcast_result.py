"""Exercise the production broadcaster over every online/send-result pair."""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / 'src/jt808.c').read_text(encoding='utf-8')
start = source.index('static int send_frame_broadcast(')
end = source.index('static int finish_frame_channel(', start)
harness = r'''
#include <stdbool.h>
#include <stdint.h>
#include <assert.h>
typedef int frame_t;
enum { TCP_CH_MAIN=0, TCP_CH_BACKUP=1 };
static bool online[2]; static int result[2]; static unsigned sent[2], released;
static bool jt808_channel_online(unsigned c) { return online[c]; }
static int send_frame_channel_delivered(frame_t *b,unsigned c) { (void)b; ++sent[c]; return result[c]; }
static void frame_release(void) { ++released; }
FUNCTION
int main(void) {
 for(unsigned mask=0;mask<4;mask++) for(unsigned failure=0;failure<4;failure++)
 {
  for(unsigned c=0;c<2;c++) {
   online[c]=(mask&(1U<<c))!=0; result[c]=(failure&(1U<<c)) ? -1:0; sent[c]=0;
  }
  released=0; frame_t b=0;
  assert(send_frame_broadcast(&b)==((online[0] && result[0]==0)?0:-1));
  assert(released==1&&sent[0]==online[0]&&sent[1]==online[1]);
 }
 return 0;
}
'''.replace('FUNCTION', source[start:end])
with tempfile.TemporaryDirectory(prefix='broadcast_') as td:
    p = Path(td)
    (p/'test.c').write_text(harness, encoding='utf-8')
    subprocess.run([shutil.which('gcc'), '-std=c99', '-Wall', '-Wextra', '-Werror',
                    str(p/'test.c'), '-o', str(p/'test.exe')], check=True)
    subprocess.run([str(p/'test.exe')], check=True)
print('broadcast result: PASS (16 online/send-result combinations)')
