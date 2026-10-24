"""Real report filter + odometer: stationary drift must never add mileage."""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HARNESS = r'''
#include "gps_report_filter.h"
#include "i2c_accel.h"
#include "flash_config.h"
#include "mileage.h"
#include <assert.h>
#include <stdio.h>

volatile uint32_t g_tick_ms;
static gps_data_t raw;
static device_config_t config;
static bool dirty;
static unsigned adds;
const gps_data_t *gps_get_data(void) { return &raw; }
bool gps_is_enabled(void) { return true; }
bool gps_is_valid(void) { return raw.valid; }
bool gps_quality_fix_fresh(void) { return raw.valid; }
device_config_t *cfg_get(void) { return &config; }
void cfg_add_mileage(uint32_t delta) {
    config.mileage_m += delta; dirty = true; ++adds;
}
bool cfg_mileage_dirty(void) { return dirty; }
bool cfg_flush_mileage(void) { dirty = false; return true; }
uint32_t cfg_persist_generation(void) { return 0; }
int dbg_printf(const char *fmt, ...) { (void)fmt; return 0; }
bool i2c_accel_read(accel_data_t *a) {
    a->x = 0; a->y = 0; a->z = 1024; return true;
}

static void step(bool new_rmc) {
    g_tick_ms += 200;
    raw.last_update_ms = g_tick_ms;
    if (new_rmc) raw.heading_update_ms = g_tick_ms;
    gps_report_filter_process(g_tick_ms);
    mileage_update();
    mileage_update(); /* Repeated main-loop calls must not add distance. */
}

int main(void) {
    config.stopdrift_en = 1; config.stopdrift_thr = 50;
    config.mileage_m = 4600;
    raw.valid = true; raw.fix_quality = 1; raw.satellites = 9;
    raw.hdop = 0.9f; raw.lat = 50; raw.lon = 10;
    raw.speed_kmh = 0.3f;
    gps_report_filter_init();
    for (unsigned i = 0; i < 180; ++i) step(i % 5 == 0);
    gps_data_t anchor, report;
    assert(gps_report_filter_copy(&raw, &anchor, g_tick_ms));
    unsigned before = config.mileage_m, calls = adds;
    assert(before == 4600 && !dirty);

    /* Two hours awake: raw drift exceeds the old 5 m mileage threshold.
     * ACC does not participate in either production module's decision. */
    for (unsigned i = 0; i < 7200 * 5; ++i) {
        raw.lat = 50 + ((i / 5) % 2 ? 0.001 : -0.001);
        raw.lon = 10 + ((i / 5) % 3 ? 0.0001 : -0.0001);
        raw.heading = (float)(i % 360);
        raw.speed_kmh = i % 2 ? 0.0f : 0.3f;
        step(i % 5 == 0);
        assert(gps_report_filter_copy(&raw, &report, g_tick_ms));
        assert(report.lat == anchor.lat && report.lon == anchor.lon);
        assert(report.speed_kmh == 0.0f && report.heading == 0.0f);
        assert(config.mileage_m == before && adds == calls && !dirty);
    }

    /* Weak speed >2 km/h must not add mileage while the report stays locked. */
    raw.hdop = 4.0f; raw.speed_kmh = 2.5f;
    for (unsigned i = 0; i < 300; ++i) {
        raw.lat = 50 + (i % 2 ? 0.001 : -0.001);
        raw.heading = (float)((i * 73) % 360);
        step(true);
        assert(gps_report_filter_copy(&raw, &report, g_tick_ms));
        assert(config.mileage_m == before && adds == calls && !dirty);
    }

    raw.valid = false;
    for (unsigned i = 0; i < 10; ++i) step(false);
    assert(config.mileage_m == before);
    raw.valid = true; raw.hdop = 0.9f; raw.speed_kmh = 0.0f;
    step(true);
    assert(gps_report_filter_copy(&raw, &report, g_tick_ms));
    assert(config.mileage_m == before);

    /* Confirm motion at a displaced raw position; never backfill the drift. */
    raw.speed_kmh = 20.0f; raw.heading = 0.0f;
    for (unsigned i = 0; i < 3; ++i) {
        raw.lat += 0.0001;
        step(true);
        assert(config.mileage_m == before);
    }
    assert(!gps_report_filter_copy(&raw, &report, g_tick_ms));
    assert(gps_report_filter_motion_pending(g_tick_ms));
    raw.lat += 0.0001;
    step(true);
    assert(config.mileage_m == before + 11 && adds == calls + 1 && dirty);
    assert(mileage_force_save(g_tick_ms) && !dirty);

    puts("PASS: two-hour stationary drift, small/weak speed, duplicate calls,");
    puts("      invalid-fix recovery, no drift backfill, movement and persistence");
    return 0;
}
'''


def main():
    cc = shutil.which("gcc")
    if not cc:
        raise RuntimeError("Host GCC is required")
    with tempfile.TemporaryDirectory(prefix="stationary_mileage_") as tmp:
        d = Path(tmp)
        (d / "n32l40x.h").write_text("#include <stdint.h>\n", encoding="ascii")
        (d / "harness.c").write_text(HARNESS, encoding="ascii")
        exe = d / "test.exe"
        subprocess.run([
            cc, "-std=c99", "-Wall", "-Wextra", "-Werror",
            "-fsanitize=undefined", "-fsanitize-undefined-trap-on-error",
            "-I", str(d), "-I", str(ROOT / "include"),
            str(d / "harness.c"), str(ROOT / "src/gps_report_filter.c"),
            str(ROOT / "src/mileage.c"), "-lm", "-o", str(exe),
        ], check=True)
        subprocess.run([str(exe)], check=True)


if __name__ == "__main__":
    main()
