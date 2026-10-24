"""Real mileage_update acceptance at exact distance-policy boundaries.

Two parts:
1. Policy: the production local_distance_m() is replaced by an injected
   distance, then the real mileage_update() is driven across the mm rounding,
   500 mm minimum, 1,000,000 mm maximum, stop-drift threshold, remainder carry
   and coordinate-range gates.
2. Accuracy: the unmodified production local_distance_m() is compared with a
   host binary64 great-circle reference (6371 km sphere) for steps up to 1 km.
"""
import math
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_mileage_persistence import HEADERS

FUNC = 'static float local_distance_m('
NEXT = '\nvoid mileage_update(void)'

POLICY_HARNESS = r'''
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include "gps.h"
#include "flash_config.h"
static gps_data_t gps;
static device_config_t config;
static unsigned added_calls;
const gps_data_t *gps_get_data(void) { return &gps; }
device_config_t *cfg_get(void) { return &config; }
void cfg_add_mileage(uint32_t delta) { config.mileage_m+=delta; ++added_calls; }
bool cfg_mileage_dirty(void) { return false; }
uint32_t cfg_persist_generation(void) { return 0; }
bool cfg_flush_mileage(void) { return true; }
uint32_t test_tick_ms(void) { return 0; }
int dbg_printf(const char *fmt, ...) { (void)fmt; return 0; }
#include "mileage_under_test.c"
static void check(float d, unsigned en, unsigned raw, float speed,
                  unsigned delta, unsigned calls, int advance) {
    s_has_first=false; s_remainder_mm=0; added_calls=0;
    memset(&config,0,sizeof config); memset(&gps,0,sizeof gps);
    config.stopdrift_en=en; config.stopdrift_thr=raw;
    gps.valid=true; gps.speed_kmh=speed;
    mileage_update();
    forced_distance=d; gps.lon_e7=10000;
    mileage_update();
    assert(config.mileage_m==delta && added_calls==calls);
    assert((s_last_lon_e7==gps.lon_e7)==advance);
    mileage_update(); /* identical fix is never charged twice */
    assert(config.mileage_m==delta && added_calls==calls);
}
int main(void) {
    /* Nearest-mm rounding at the 500 mm exclusive minimum. */
    check(0.5004f,0,50,0,0,0,1);
    check(0.5006f,0,50,0,0,0,1);      /* 501 mm kept as remainder only */
    check(0.9996f,0,50,0,1,1,1);      /* rounds to 1000 mm */
    /* 1,000,000 mm exclusive maximum. */
    check(999.9994f,0,50,0,999,1,1);
    check(999.9996f,0,50,0,0,0,1);
    check(1000.0f,0,50,0,0,0,1);
    /* Stop-drift threshold raw/10 m, below 2 km/h only; rejection keeps baseline. */
    check(4.9994f,1,50,0,0,0,0);
    check(4.9996f,1,50,0,5,1,1);
    check(5.0f,1,50,0,5,1,1);
    check(1.0f,1,50,2,1,1,1);
    /* Largest raw threshold; values kept clear of binary32 mm spacing (0.5 mm). */
    check(6553.49f,1,65535,0,0,0,0);
    check(6553.51f,1,65535,0,0,0,1);
    /* Over-range distance is clamped to 8192 m, then rejected as a jump. */
    check(1e20f,1,65535,0,0,0,1);
    check(INFINITY,0,0,0,0,0,1);
    /* Non-finite/negative distances are refused without moving the baseline. */
    check(NAN,0,0,0,0,0,0);
    check(-1.0f,0,0,0,0,0,0);
    /* Adjacent binary32 values around an exactly representable half mm. */
    check(nextafterf(0.0625f,0),1,1,0,0,0,0);
    check(nextafterf(0.0625f,1),1,1,0,0,0,0);
    /* Remainder carry: 3 x 600 mm = 1 m + 800 mm, then 200 mm more is <=500. */
    s_has_first=false; s_remainder_mm=0; added_calls=0;
    memset(&config,0,sizeof config); memset(&gps,0,sizeof gps);
    gps.valid=true; gps.speed_kmh=20; mileage_update();
    forced_distance=0.6f;
    for (int i=1;i<=3;++i) { gps.lon_e7=i*100; mileage_update(); }
    assert(config.mileage_m==1 && s_remainder_mm==800 && added_calls==1);
    forced_distance=0.2f; gps.lon_e7=400; mileage_update();
    assert(config.mileage_m==1 && s_remainder_mm==800);
    forced_distance=0.7f; gps.lon_e7=500; mileage_update();
    assert(config.mileage_m==2 && s_remainder_mm==500 && added_calls==2);
    /* Coordinate gates on the integer e7 fix. */
    memset(&gps,0,sizeof gps);
    s_has_first=false; gps.valid=true; gps.lat_e7=GPS_LAT_E7_MAX+1; mileage_update(); assert(!s_has_first);
    gps.lat_e7=-GPS_LAT_E7_MAX-1; mileage_update(); assert(!s_has_first);
    gps.lat_e7=0; gps.lon_e7=GPS_LON_E7_MAX+1; mileage_update(); assert(!s_has_first);
    gps.lon_e7=INT32_MIN; mileage_update(); assert(!s_has_first);
    gps.lon_e7=0; gps.valid=false; mileage_update(); assert(!s_has_first);
    gps.valid=true; mileage_update(); assert(s_has_first);
    gps.lat_e7=GPS_LAT_E7_MAX; gps.lon_e7=-GPS_LON_E7_MAX;
    s_has_first=false; mileage_update(); assert(s_has_first);
    puts("quantization boundaries, carry, repeat fixes and invalid inputs PASS");
    return 0;
}
'''

ACCURACY_HARNESS = r'''
#include <math.h>
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include "gps.h"
#include "distance_under_test.c"
int main(void) {
    long a,b,c,d;
    while (scanf("%ld %ld %ld %ld",&a,&b,&c,&d)==4)
        printf("%.9g\n",(double)local_distance_m((int32_t)a,(int32_t)b,(int32_t)c,(int32_t)d));
    return 0;
}
'''

R = 6371000.0


def great_circle(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(min(1.0, math.sqrt(h)))


def destination(lat, lon, metres, bearing):
    phi, lam, th, arc = map(math.radians, (lat, lon, bearing, 0.0))
    arc = metres / R
    p = math.asin(max(-1.0, min(1.0, math.sin(phi) * math.cos(arc) +
                                math.cos(phi) * math.sin(arc) * math.cos(th))))
    l = lam + math.atan2(math.sin(th) * math.sin(arc) * math.cos(phi),
                         math.cos(arc) - math.sin(phi) * math.sin(p))
    return math.degrees(p), (math.degrees(l) + 180) % 360 - 180


def e7(x):
    return int(round(x * 1e7))


def accuracy_cases():
    rng = random.Random(406)
    rows = []
    # Production-relevant latitudes; the projection is not claimed near the poles.
    for _ in range(20000):
        lat = rng.uniform(-80, 80)
        lon = rng.uniform(-180, 180)
        dist = 10 ** rng.uniform(-0.3, 3)  # 0.5 m .. 1 km
        lat2, lon2 = destination(lat, lon, dist, rng.uniform(0, 360))
        rows.append((e7(lat), e7(lon), e7(lat2), e7(lon2)))
    for lat in (-80, -60, -45, 0, 22.5, 45, 60, 80):
        for bearing in (0, 45, 90, 135, 180, 270):
            for dist in (0.5, 1, 5, 10, 100, 999, 1000):
                # Dateline crossing on both sides.
                lat2, lon2 = destination(lat, 179.9999, dist, bearing)
                rows.append((e7(lat), e7(179.9999), e7(lat2), e7(lon2)))
                lat2, lon2 = destination(lat, -179.9999, dist, bearing)
                rows.append((e7(lat), e7(-179.9999), e7(lat2), e7(lon2)))
    return [r for r in rows if abs(r[2]) <= 900000000]


def compile_run(cc, folder, src, exe, stdin=None):
    subprocess.run([cc, '-std=c99', '-Os', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=undefined', '-fsanitize-undefined-trap-on-error',
                    '-I', str(folder), str(src), '-lm', '-o', str(exe)], check=True)
    return subprocess.run([str(exe)], check=True, input=stdin,
                          capture_output=stdin is not None, text=True)


def main():
    cc = shutil.which('gcc')
    if not cc:
        raise RuntimeError('host GCC required')
    source = (ROOT / 'src/mileage.c').read_text(encoding='utf-8')
    start = source.index(FUNC)
    end = source.index(NEXT, start)
    distance_fn = source[start:end]
    policy = source[:start] + '''static float forced_distance;
static float local_distance_m(int32_t a, int32_t b, int32_t c, int32_t d)
{ (void)a; (void)b; (void)c; (void)d; return forced_distance; }
''' + source[end:]
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        for name, content in HEADERS.items():
            (folder / name).write_text(content, encoding='utf-8')
        (folder / 'mileage_under_test.c').write_text(policy, encoding='utf-8')
        (folder / 'distance_under_test.c').write_text(distance_fn, encoding='utf-8')
        (folder / 'policy.c').write_text(POLICY_HARNESS, encoding='ascii')
        (folder / 'accuracy.c').write_text(ACCURACY_HARNESS, encoding='ascii')
        compile_run(cc, folder, folder / 'policy.c', folder / 'policy.exe')

        rows = accuracy_cases()
        wire = ''.join('%d %d %d %d\n' % r for r in rows)
        out = compile_run(cc, folder, folder / 'accuracy.c', folder / 'accuracy.exe', wire)
        got = [float(x) for x in out.stdout.split()]
        assert len(got) == len(rows)
        worst_rel = worst_abs = 0.0
        for r, d in zip(rows, got):
            ref = great_circle(r[0] / 1e7, r[1] / 1e7, r[2] / 1e7, r[3] / 1e7)
            err = abs(d - ref)
            assert err <= max(1e-4 * ref, 0.002), (r, ref, d)
            worst_abs = max(worst_abs, err)
            if ref > 1:
                worst_rel = max(worst_rel, err / ref)
        print('local_distance_m vs great circle: %d steps <=1 km, max_abs=%.4g m, max_rel=%.3g PASS'
              % (len(rows), worst_abs, worst_rel))


if __name__ == '__main__':
    main()
