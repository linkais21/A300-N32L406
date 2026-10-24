"""Real mileage_update acceptance at exact distance-policy boundaries."""
import sys
from pathlib import Path
import tempfile
import subprocess
import shutil

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools/experiments'))
import firmware_size_trial as trial
from replay_mileage_size_trial import HARNESS, persist

def main():
    source = (ROOT/'src/mileage.c').read_text(encoding='utf-8')
    # Test the integrated production policy, not a generated candidate.
    start = source.index('static double haversine_m(')
    end = source.index('\nvoid mileage_update(void)', start)
    source = source[:start] + '''static double forced_distance;
static double haversine_m(double a, double b, double c, double d)
{ (void)a; (void)b; (void)c; (void)d; return forced_distance; }
''' + source[end:]
    # Remove the bounded helper rendered unused by distance injection.
    if 'static double mileage_trial_sin(' in source:
        a = source.index('static double mileage_trial_sin(')
        b = source.index('static double forced_distance;', a)
        source = source[:a] + source[b:]
    harness = HARNESS.split('int main(void)', 1)[0] + r'''
#include <assert.h>
static void check(double d, unsigned en, unsigned raw, float speed,
                  unsigned delta, unsigned calls, int advance) {
    s_has_first=false; added_calls=0;
    memset(&config,0,sizeof config); memset(&gps,0,sizeof gps);
    config.stopdrift_en=en; config.stopdrift_thr=raw;
    gps.valid=true; gps.speed_kmh=speed;
    mileage_update();
    forced_distance=d; gps.lon=0.001;
    mileage_update();
    assert(config.mileage_m==delta && added_calls==calls);
    assert((s_last_lon==gps.lon)==advance);
    mileage_update();
    assert(config.mileage_m==delta && added_calls==calls);
}
int main(void) {
    check(0.5004,0,50,0,0,0,1);
    check(0.5006,0,50,0,0,1,1);
    check(0.9996,0,50,0,1,1,1);
    check(999.9994,0,50,0,999,1,1);
    check(999.9996,0,50,0,0,0,1);
    check(1000,0,50,0,0,0,1);
    check(4.9994,1,50,0,0,0,0);
    check(4.9996,1,50,0,5,1,1);
    check(5,1,50,0,5,1,1);
    check(1,1,50,2,1,1,1);
    check(6553.4994,1,65535,0,0,0,0);
    check(6553.4996,1,65535,0,0,0,1);
    check(1e20,1,65535,0,0,0,1);
    check(NAN,0,0,0,0,0,0);
    check(INFINITY,0,0,0,0,0,0);
    check(-1,0,0,0,0,0,0);
    /* Adjacent binary64 values around an exactly representable half mm. */
    check(nextafter(0.0625,0),1,1,0,0,0,0);
    check(nextafter(0.0625,1),1,1,0,0,0,0);
    s_has_first=false; gps.lat=NAN; mileage_update(); assert(!s_has_first);
    gps.lat=91; mileage_update(); assert(!s_has_first);
    gps.lat=0; gps.lon=181; mileage_update(); assert(!s_has_first);
    gps.lon=0; gps.valid=false; mileage_update(); assert(!s_has_first);
    gps.valid=true; mileage_update(); assert(s_has_first);
    puts("quantization boundaries, repeat fixes and invalid inputs PASS");
    return 0;
}
'''
    with tempfile.TemporaryDirectory() as tmp:
        folder=Path(tmp)
        for name, content in persist.HEADERS.items(): (folder/name).write_text(content)
        (folder/'mileage_under_test.c').write_text(source,encoding='utf-8')
        (folder/'test.c').write_text(harness)
        subprocess.run([shutil.which('gcc'),'-std=c99','-Os','-Wall','-Wextra','-Werror','-I',str(folder),str(folder/'test.c'),'-lm','-o',str(folder/'test.exe')],check=True)
        subprocess.run([str(folder/'test.exe')],check=True)

if __name__=='__main__': main()
