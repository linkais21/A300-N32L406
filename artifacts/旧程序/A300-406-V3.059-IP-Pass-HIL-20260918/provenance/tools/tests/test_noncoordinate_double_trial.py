"""Check real altitude encoder against its existing double contract."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments'))
import noncoordinate_double_trial as trial
from test_f39_actions import find_compiler


class AltitudeContract(unittest.TestCase):
    def test_binary32_replay(self):
        original = (trial.ROOT / 'src/jt808.c').read_text(encoding='utf-8')
        baseline = trial.altitude_function(original).replace('altitude_extension_tail', 'baseline')
        exact = trial.altitude_function(trial.transform(original, 'altitude_exact')).replace('altitude_extension_tail', 'candidate')
        floating = trial.altitude_function(trial.transform(original, 'altitude_float')).replace('altitude_extension_tail', 'floating')
        harness = r'''
#include <stdint.h>
#include <string.h>
#include <math.h>
#include <assert.h>
#include <stdio.h>
''' + baseline + exact + floating + r'''
static unsigned count, different;
static void check(uint32_t bits) {
 float a; memcpy(&a,&bits,4);
 assert(baseline(a)==candidate(a));
 if(baseline(a)!=floating(a) && different<4)
   printf("float_difference bits=0x%08x altitude=%.9g baseline=%u float=%u\n",
          (unsigned)bits,(double)a,(unsigned)baseline(a),(unsigned)floating(a));
 different += baseline(a)!=floating(a); ++count;
}
int main(void) {
 /* Every exponent/sign, mantissa edges, deterministic random bit patterns. */
 for(uint32_t e=0;e<512;e++) {
   for(uint32_t m=0;m<1024;m++) {
     check((e<<23)|m); check((e<<23)|(0x7fffffU-m));
   }
 }
 uint32_t seed=0xDB101U;
 for(unsigned i=0;i<1000000;i++) {seed=seed*1664525U+1013904223U;check(seed);}
 /* Float neighbours around every mm boundary over 0..1000 m. */
 for(unsigned i=0;i<=1000000;i++) {
   float a=(float)((double)i/1000.0); uint32_t bits;memcpy(&bits,&a,4);
   check(bits);check(bits+1);if(bits)check(bits-1);
 }
 assert(different>0); /* negative control must detect unsafe float rounding */
 printf("altitude samples=%u exact_mismatches=0 float_mismatches=%u\n",count,different);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p/'test.c').write_text(harness, encoding='utf-8')
            subprocess.run([find_compiler(), '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                            str(p/'test.c'), '-lm', '-o', str(p/'test.exe')], check=True)
            subprocess.run([str(p/'test.exe')], check=True)


if __name__ == '__main__':
    unittest.main()
