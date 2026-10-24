"""Real-C odometer: retain accepted millimetres without crediting rejected fixes."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

from test_mileage_persistence import HEADERS

ROOT = Path(__file__).resolve().parents[2]
HARNESS = r'''
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include "gps.h"
#include "flash_config.h"
static gps_data_t gps;
static device_config_t config;
static bool locked, dirty;
static unsigned adds;
const gps_data_t *gps_get_data(void) { return &gps; }
device_config_t *cfg_get(void) { return &config; }
void cfg_add_mileage(uint32_t metres) {
    assert(metres != 0U);
    config.mileage_m += metres; dirty = true; ++adds;
}
bool cfg_mileage_dirty(void) { return dirty; }
bool cfg_flush_mileage(void) { dirty = false; return true; }
uint32_t cfg_persist_generation(void) { return 0U; }
uint32_t test_tick_ms(void) { return 0U; }
int dbg_printf(const char *format, ...) { (void)format; return 0; }
bool gps_report_filter_copy(const gps_data_t *raw, gps_data_t *out, uint32_t now) {
    (void)now; *out = *raw; return locked;
}
#include "mileage_under_test.c"
#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
static int32_t e7(double metres) {
    return (int32_t)llround(metres / 6371000.0 * (180.0 / M_PI) * 1e7);
}
static void at(double metres) {
    gps.valid = true;
    gps.lat_e7 = e7(metres);
    gps.lon_e7 = 0;
    gps.speed_kmh = 38.88f;
    mileage_update();
}
/* Integer e7 steps along a meridian: exact inputs on the firmware grid.
 * Reference metres come from the great circle on the 6371 km sphere. */
static int32_t walk_e7;
static uint32_t ref_mm(int32_t units) {
    return (uint32_t)llround(6371000.0 * (units * 1e-7) * (M_PI / 180.0) * 1000.0);
}
static void step_e7(int32_t units) {
    walk_e7 += units;
    gps.valid = true; gps.lat_e7 = walk_e7; gps.lon_e7 = 0;
    gps.speed_kmh = 38.88f;
    mileage_update();
}
int main(int argc, char **argv) {
    assert(argc == 2);
    at(0.0);
    if (!strcmp(argv[1], "route")) {
        /* 971 e7 = 10.797 m: each step floors to 10 m; carry must keep mm. */
        assert(ref_mm(971) == 10797U);
        for (unsigned i = 1; i <= 1000; ++i) {
            step_e7(971);
            unsigned once = config.mileage_m, calls = adds;
            mileage_update(); mileage_update();
            assert(config.mileage_m == once && adds == calls);
        }
        printf("1000 x 10.797 m: expected=10797 actual=%u m\n", config.mileage_m);
        fflush(stdout);
        assert(config.mileage_m == 10797U);
    } else if (!strcmp(argv[1], "submetre")) {
        /* 54 e7 = 0.6005 m -> 600 mm per step; 1000 steps earn 600 m. */
        assert(ref_mm(54) == 600U);
        for (unsigned i = 1; i <= 1000; ++i) step_e7(54);
        assert(config.mileage_m == 600U && adds == 600U);
    } else if (!strcmp(argv[1], "mixed")) {
        /* Alternating fractional steps (~12.876 m / ~7.128 m). */
        uint32_t expected_mm = 0;
        for (unsigned i = 0; i < 1000; ++i) {
            int32_t units = i % 2 ? 641 : 1158;
            expected_mm += ref_mm(units);
            step_e7(units);
        }
        assert(expected_mm == 10002000U);
        assert(config.mileage_m == expected_mm / 1000U);
    } else if (!strcmp(argv[1], "invalid")) {
        at(0.6);
        assert(config.mileage_m == 0U && !dirty);
        gps.valid = false; gps.lat_e7 = 10000000; mileage_update();
        gps.valid = true; gps.lat_e7 = 910000000; mileage_update(); /* 91 deg */
        gps.lat_e7 = 0; gps.lon_e7 = -1810000000; mileage_update(); /* -181 deg */
        gps.lon_e7 = 0;
        assert(config.mileage_m == 0U && !dirty);
        at(1.2);
        assert(config.mileage_m == 1U);
    } else if (!strcmp(argv[1], "stationary")) {
        at(0.6);
        locked = true;
        for (unsigned i = 0; i < 100; ++i) at(i % 2 ? 500 : 1500);
        assert(config.mileage_m == 0U && !dirty && adds == 0U);
        locked = false;
        at(1500); /* First released fix only seeds a baseline. */
        assert(config.mileage_m == 0U);
        at(1500.6);
        assert(config.mileage_m == 1U); /* Prior earned fraction survives. */
    } else if (!strcmp(argv[1], "rejected")) {
        at(0.6);
        at(1500.6); /* Existing >=1 km jump rejection, with baseline advance. */
        assert(config.mileage_m == 0U && !dirty);
        at(1501.2);
        assert(config.mileage_m == 1U);
        at(1501.45); /* Existing <=0.5 m rejection must not earn fractions. */
        at(1502.05);
        assert(config.mileage_m == 1U);
        at(1502.65);
        assert(config.mileage_m == 2U);
    } else if (!strcmp(argv[1], "drift")) {
        at(0.6);
        config.stopdrift_en = 1; config.stopdrift_thr = 50;
        gps.lat_e7 = e7(1.2);
        gps.speed_kmh = 0.5f; mileage_update();
        assert(config.mileage_m == 0U && !dirty);
        gps.speed_kmh = 10; mileage_update();
        assert(config.mileage_m == 1U);
    } else if (!strcmp(argv[1], "restart")) {
        config.mileage_m = 123456U;
        at(0.6); /* Fresh process: no carried fractions from previous boot. */
        assert(config.mileage_m == 123456U && !dirty);
        at(1.2);
        assert(config.mileage_m == 123457U);
    } else { assert(0); }
    printf("%s: PASS\n", argv[1]);
    return 0;
}
'''


def main():
    cc = os.environ.get("CC") or shutil.which("gcc")
    if not cc:
        raise RuntimeError("Host GCC is required")
    headers = dict(HEADERS)
    headers["gps_report_filter.h"] = '#include "gps.h"\n#include <stdint.h>\nbool gps_report_filter_copy(const gps_data_t *, gps_data_t *, uint32_t);\n'
    with tempfile.TemporaryDirectory(prefix="mileage_fractional_") as tmp:
        folder = Path(tmp)
        for name, content in headers.items():
            (folder / name).write_text(content, encoding="ascii")
        (folder / "mileage_under_test.c").write_bytes((ROOT / "src/mileage.c").read_bytes())
        (folder / "test.c").write_text(HARNESS, encoding="ascii")
        exe = folder / "test.exe"
        subprocess.run([cc, "-std=c99", "-Os", "-Wall", "-Wextra", "-Werror",
                        "-fsanitize=undefined", "-fsanitize-undefined-trap-on-error",
                        "-I", str(folder), str(folder / "test.c"), "-lm", "-o", str(exe)], check=True)
        for case in ["route", "submetre", "mixed", "invalid", "stationary", "rejected", "drift", "restart"]:
            subprocess.run([str(exe), case], check=True)


if __name__ == "__main__":
    main()
