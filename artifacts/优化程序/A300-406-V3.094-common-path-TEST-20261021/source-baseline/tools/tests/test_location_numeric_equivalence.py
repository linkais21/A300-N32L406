"""Compile production predicates/calendar and compare pre-size-refactor semantics."""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def function(source, name):
    start = source.index(name + '(')
    # Skip prototypes if a declaration precedes the definition.
    while source.find(';', start) < source.find('{', start):
        start = source.index(name + '(', start + len(name))
    brace = source.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def main():
    report = (ROOT / 'src/gps_report_filter.c').read_text(encoding='utf-8')
    jt = (ROOT / 'src/jt808.c').read_text(encoding='utf-8')
    code = r'''
#include "gps.h"
#include <assert.h>
#include <math.h>
#include <stdint.h>
#include <string.h>
#define REPORT_FIX_MAX_AGE_MS 3000u
bool gps_is_valid(void) { return true; }
'''
    code += 'static bool ' + function(report, 'report_fix_fresh') + '\n'
    code += 'static uint8_t ' + function(jt, 'jt808_days_in_month') + '\n'
    code += 'bool ' + function(jt, 'jt808_location_snapshot_valid') + '\n'
    code += r'''
static bool old_fresh(const gps_data_t *g, uint32_t now) {
 return g && g->valid && isfinite(g->lat) && isfinite(g->lon) &&
   g->lat >= -90.0 && g->lat <= 90.0 && g->lon >= -180.0 && g->lon <= 180.0 &&
   isfinite(g->speed_kmh) && g->speed_kmh >= 0.0f &&
   now-g->last_update_ms <= 3000u && now-g->heading_update_ms <= 3000u;
}
static uint64_t seed=0x123456789abcdefULL;
static double next_double(void) {
 seed^=seed<<13; seed^=seed>>7; seed^=seed<<17;
 double d; memcpy(&d,&seed,sizeof(d)); return d;
}
int main(void) {
 gps_data_t g={0}; g.valid=true; g.fix_quality=1;
 const double edge[]={0.0,-0.0,90.0,-90.0,180.0,-180.0,
  INFINITY,-INFINITY,NAN,0x1p-1074,-0x1p-1074,
  0x1.6800000000001p6,-0x1.6800000000001p6,
  0x1.6800000000001p7,-0x1.6800000000001p7};
 for(unsigned i=0;i<sizeof(edge)/sizeof(edge[0]);++i)
  for(unsigned j=0;j<sizeof(edge)/sizeof(edge[0]);++j) {
   g.lat=edge[i];g.lon=edge[j];
   assert(old_fresh(&g,0)==report_fix_fresh(&g,0));
  }
 assert(!report_fix_fresh(NULL,0));
 for(unsigned i=0;i<300000;++i) {
  g.lat=next_double();g.lon=next_double();
  assert(old_fresh(&g,0)==report_fix_fresh(&g,0));
  /* Retained GPS rejects with >, mileage accepts with <=. Keep their
     existing unordered-NaN behavior distinct instead of broadening scope. */
  assert((g.lat < -90.0 || g.lat > 90.0)==(fabs(g.lat)>90.0));
  assert((g.lon < -180.0 || g.lon > 180.0)==(fabs(g.lon)>180.0));
  assert((g.lat>=-90.0 && g.lat<=90.0)==(fabs(g.lat)<=90.0));
  assert((g.lon>=-180.0 && g.lon<=180.0)==(fabs(g.lon)<=180.0));
 }
 static const uint8_t days[]={0,31,28,31,30,31,30,31,31,30,31,30,31};
 for(unsigned year=2000;year<=65535;++year) {
  g.year=(uint16_t)year;
  for(unsigned month=1;month<=12;++month) {
   unsigned expected=days[month]+(month==2 &&
     ((year%4==0 && year%100!=0) || year%400==0));
   g.month=(uint8_t)month;
   assert(jt808_days_in_month(g.year,g.month)==expected);
   g.day=(uint8_t)expected;assert(jt808_location_snapshot_valid(&g,0));
   g.day=(uint8_t)(expected+1);assert(!jt808_location_snapshot_valid(&g,0));
   g.day=0;assert(!jt808_location_snapshot_valid(&g,0));
  }
 }
 g.year=2026;g.month=0;g.day=1;assert(!jt808_location_snapshot_valid(&g,0));
 g.month=13;assert(!jt808_location_snapshot_valid(&g,0));
 assert(!jt808_location_snapshot_valid(NULL,0));
 return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='location_numeric_') as td:
        d = Path(td)
        (d/'n32l40x.h').write_text('#include <stdint.h>\n')
        (d/'test.c').write_text(code)
        subprocess.run([shutil.which('gcc'), '-std=c99', '-O2', '-Wall', '-Wextra',
                        '-Werror', '-fsanitize=undefined', '-fsanitize-undefined-trap-on-error',
                        '-I', str(d), '-I', str(ROOT/'include'), str(d/'test.c'),
                        '-lm', '-o', str(d/'test.exe')], check=True, timeout=60)
        subprocess.run([str(d/'test.exe')], check=True, timeout=30)
    print('PASS: numeric boundaries, 300000 IEEE inputs, all uint16 years >=2000')


if __name__ == '__main__':
    main()
