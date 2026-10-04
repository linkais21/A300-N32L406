"""Host regression for bounded mileage persistence scheduling."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]

HARNESS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#include "gps.h"
#include "flash_config.h"
#include "mileage.h"

static gps_data_t gps;
static device_config_t config;
static uint32_t now_ms;
static bool dirty;
static bool flush_ok = true;
static unsigned flush_count;
static uint32_t persist_generation;

const gps_data_t *gps_get_data(void) { return &gps; }
device_config_t *cfg_get(void) { return &config; }
void cfg_add_mileage(uint32_t delta_m)
{ config.mileage_m += delta_m; dirty = true; }
bool cfg_mileage_dirty(void) { return dirty; }
uint32_t cfg_persist_generation(void) { return persist_generation; }
bool cfg_flush_mileage(void)
{
    ++flush_count;
    if (!flush_ok) return false;
    dirty = false;
    ++persist_generation;
    return true;
}
uint32_t test_tick_ms(void) { return now_ms; }
int dbg_printf(const char *fmt, ...) { (void)fmt; return 0; }

static void point(double lat, double lon)
{
    gps.valid = true;
    gps.lat = lat;
    gps.lon = lon;
    gps.speed_kmh = 20.0f;
}

int main(void)
{
    point(0.0, 0.0);
    mileage_update();
    mileage_update();
    assert(config.mileage_m == 0U);
    point(0.001, 0.0);
    mileage_update();
    {
        uint32_t once = config.mileage_m;
        mileage_update();
        assert(config.mileage_m == once);
    }
    assert(config.mileage_m > 100U);
    assert(dirty && flush_count == 0U);

    mileage_persist_process(0U);
    mileage_persist_process(599999U);
    assert(flush_count == 0U);
    mileage_persist_process(600000U);
    assert(flush_count == 1U && !dirty);

    point(0.002, 0.0);
    mileage_update();
    mileage_persist_process(600001U);
    assert(flush_count == 1U && dirty);

    /* A later config save persists the current mileage, but the next main
     * loop adds more distance before the scheduler observes a clean dirty
     * flag. The persisted epoch must invalidate the old 10-minute deadline. */
    dirty = false;
    ++persist_generation;
    point(0.003, 0.0);
    mileage_update();
    mileage_persist_process(1200001U);
    assert(flush_count == 1U && dirty);
    mileage_persist_process(1800000U);
    assert(flush_count == 1U);
    mileage_persist_process(1800001U);
    assert(flush_count == 2U && !dirty);

    point(0.004, 0.0);
    mileage_update();
    flush_ok = false;
    mileage_persist_process(1800002U);
    mileage_persist_process(2400001U);
    assert(flush_count == 2U);
    mileage_persist_process(2400002U);
    assert(flush_count == 3U && dirty);
    mileage_persist_process(2430001U);
    assert(flush_count == 3U);

    flush_ok = true;
    assert(!mileage_force_save(2430001U));
    assert(flush_count == 3U && dirty);
    assert(mileage_force_save(2430002U));
    assert(flush_count == 4U && !dirty);
    {
        uint32_t saved = config.mileage_m;
        mileage_update();
        assert(config.mileage_m == saved);
    }
    puts("test_mileage_persistence: PASS");
    return 0;
}
'''


HEADERS = {
    "config.h": "#ifndef CONFIG_H\n#define CONFIG_H\n#define ADC_CAR_CH 0\n#define ADC_BAT_CH 1\n#endif\n",
    "gps.h": r'''#ifndef GPS_H
#define GPS_H
#include <stdbool.h>
typedef struct { bool valid; double lat, lon; float heading, speed_kmh; } gps_data_t;
const gps_data_t *gps_get_data(void);
#endif
''',
    "flash_config.h": r'''#ifndef FLASH_CONFIG_H
#define FLASH_CONFIG_H
#include <stdint.h>
#include <stdbool.h>
typedef struct { uint8_t stopdrift_en; uint16_t stopdrift_thr; uint32_t mileage_m; } device_config_t;
device_config_t *cfg_get(void);
void cfg_add_mileage(uint32_t delta_m);
bool cfg_mileage_dirty(void);
uint32_t cfg_persist_generation(void);
bool cfg_flush_mileage(void);
#endif
''',
    "hw_init.h": "#ifndef HW_INIT_H\n#define HW_INIT_H\n#include <stdint.h>\nuint32_t test_tick_ms(void);\n#define TICK_MS() test_tick_ms()\n#endif\n",
    "debug_uart.h": "#ifndef DEBUG_UART_H\n#define DEBUG_UART_H\nint dbg_printf(const char *fmt, ...);\n#endif\n",
    "jt808.h": "#ifndef JT808_H\n#define JT808_H\n#endif\n",
    "n32l40x.h": "#ifndef N32L40X_H\n#define N32L40X_H\n#endif\n",
}


def main() -> None:
    cc = os.environ.get("CC") or shutil.which("gcc") or shutil.which("cc")
    if not cc:
        raise AssertionError("host C compiler is required")
    with tempfile.TemporaryDirectory(prefix="mileage_persist_") as td:
        directory = Path(td)
        for name, content in HEADERS.items():
            (directory / name).write_text(content, encoding="ascii")
        harness = directory / "harness.c"
        output = directory / "mileage.exe"
        harness.write_text(HARNESS, encoding="ascii")
        build = subprocess.run(
            [cc, "-std=c99", "-Wall", "-Wextra", "-Werror",
             "-I", str(directory), "-I", str(ROOT / "include"), str(harness), str(ROOT / "src" / "mileage.c"),
             "-lm", "-o", str(output)],
            cwd=ROOT, capture_output=True, text=True,
        )
        if build.returncode:
            raise AssertionError("mileage harness compile failed:\n" + build.stderr)
        run = subprocess.run([str(output)], cwd=ROOT,
                             capture_output=True, text=True)
        if run.returncode:
            raise AssertionError("mileage harness failed:\n" + run.stdout + run.stderr)
        print(run.stdout.strip())


if __name__ == "__main__":
    main()
