"""Check real altitude encoder against its existing double contract."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments'))
import noncoordinate_double_trial as trial
from test_f39_actions import find_compiler


# Original binary64 encoder (pre-fixed-point src/jt808.c), kept as the oracle.
REFERENCE = r'''static uint16_t baseline(float altitude)
{
    double scaled = fabs((double)altitude) * 1000.0;
    if (!(scaled < 4294967296.0)) return 0U;
    return (uint16_t)(((uint32_t)scaled) % 1000U);
}
'''

# Naive single-precision rewrite: negative control that must be detected.
FLOAT_CONTROL = r'''static uint16_t floating(float altitude)
{
    float scaled = fabsf(altitude) * 1000.0f;
    if (!(scaled < 4294967296.0f)) return 0U;
    return (uint16_t)(((uint32_t)scaled) % 1000U);
}
'''


class AltitudeContract(unittest.TestCase):
    def test_binary32_replay(self):
        production_source = (trial.ROOT / 'src/jt808.c').read_text(encoding='utf-8')
        # The binary64 contract is now a fixed oracle: production no longer
        # links soft-double, so the original encoder is kept in this test.
        baseline = REFERENCE
        exact = trial.EXACT.replace('altitude_extension_tail', 'candidate')
        floating = FLOAT_CONTROL
        production = trial.altitude_function(production_source).replace(
            'altitude_extension_tail', 'production')
        harness = r'''
#include <stdint.h>
#include <string.h>
#include <math.h>
#include <assert.h>
#include <stdio.h>
''' + baseline + exact + floating + production + r'''
static unsigned count, different, production_different;
static void check(uint32_t bits) {
 float a; memcpy(&a,&bits,4);
 assert(baseline(a)==candidate(a));
 if(baseline(a)!=production(a) && production_different<4)
   printf("production_difference bits=0x%08x altitude=%.9g contract=%u production=%u\n",
          (unsigned)bits,(double)a,(unsigned)baseline(a),(unsigned)production(a));
 fflush(stdout);
 production_different += baseline(a)!=production(a);
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
 printf("altitude samples=%u exact_mismatches=0 float_mismatches=%u production_mismatches=%u\n",
        count,different,production_different);
 fflush(stdout);
 /* Production must keep the exact floor(|alt|*1000)%1000 wire contract. */
 assert(production_different==0);
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
