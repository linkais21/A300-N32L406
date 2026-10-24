#include "config.h"
#include "gps.h"
#include "gps_report_filter.h"
#include "jt808.h"
#include "flash_config.h"
#include "hw_init.h"
#include "debug_uart.h"
#ifndef DBG_PRINTF_VERBOSE
#define DBG_PRINTF_VERBOSE(...) dbg_printf(__VA_ARGS__)
#endif
#include "n32l40x.h"
#include <math.h>
#include <string.h>

/*
 * mileage.c — fixed-point odometer, stop-drift filter and persistence
 *
 * Stop-drift filter:
 *   When enabled, speed < 2.0 km/h AND distance from the last accepted
 *   position < stopdrift_thr / 10.0 metres rejects the update.
 *   Default raw 50 therefore means 5 m in this implementation.
 *   The external protocol unit is unconfirmed; preserve stored values and
 *   this conversion until the protocol/configuration contract is verified.
 */

static int32_t s_last_lat_e7 = 0;
static int32_t s_last_lon_e7 = 0;
static float  s_last_hdg  = 0.0f;
static bool   s_has_first = false;
/* Earned travel only: keep across stops, never add rejected drift/jumps.
 * RAM-only remainder preserves the stored metre/JT808/Flash format. A reset
 * can discard at most 999 mm here; whole-metre persistence is unchanged. */
static uint16_t s_remainder_mm;
#define MILEAGE_PERSIST_INTERVAL_MS (600000UL)
#define MILEAGE_RETRY_BACKOFF_MS    (30000UL)
static bool s_persist_schedule_armed;
static bool s_retry_backoff_active;
static uint32_t s_persist_due_ms;
static uint32_t s_seen_persist_generation;

/* ── Local distance (metres) ─────────────────────────────────────────────── */
/* Equirectangular projection at the mean latitude. Mileage only accepts
 * steps below 1 km and caps at 8192 m, where the error against a great
 * circle stays below 1e-4 relative. Integer deltas keep 1e-7 deg resolution
 * and the single-precision FPU does the rest. */
static float local_distance_m(int32_t lat1, int32_t lon1, int32_t lat2, int32_t lon2)
{
    float north = (float)(lat2 - lat1) * GPS_M_PER_E7;
    float east = (float)gps_lon_delta_e7(lon1, lon2) *
                 (GPS_M_PER_E7 * gps_cos_lat_e7((int32_t)(((int64_t)lat1 + lat2) / 2)));
    float a = north * north + east * east;
    if (a >= 8192.0f * 8192.0f) return 8192.0f;
    return sqrtf(a);
}


void mileage_update(void)
{
    const gps_data_t *g = gps_get_data();
    if (!g->valid || !gps_coord_in_range(g)) return;

    /* Share the live report's stationary decision, independent of ACC/sleep.
     * Discard the old distance baseline so releasing the lock never charges
     * the anchor-to-raw drift as travel. The first moving fix starts anew. */
    gps_data_t report;
    if (gps_report_filter_copy(g, &report, TICK_MS())) {
        s_has_first = false;
        return;
    }

    device_config_t *c = cfg_get();

    if (!s_has_first) {
        s_last_lat_e7 = g->lat_e7;
        s_last_lon_e7 = g->lon_e7;
        s_last_hdg  = g->heading;
        s_has_first = true;
        return;
    }

    /* The main loop may run several times before GPS publishes a new fix.
     * Reusing the exact same coordinates must not pay for the distance
     * again or re-evaluate the same sample. */
    if (g->lat_e7 == s_last_lat_e7 && g->lon_e7 == s_last_lon_e7)
        return;

    float dist_m = local_distance_m(s_last_lat_e7, s_last_lon_e7, g->lat_e7, g->lon_e7);

    /* Mileage policy: nearest millimetre, positive halfway up. */
    if (!(dist_m >= 0.0f)) return;
    if (dist_m > 8192.0f) dist_m = 8192.0f;
    uint32_t dist_mm = (uint32_t)(dist_m * 1000.0f + 0.5f);
    uint32_t threshold_mm = (uint32_t)c->stopdrift_thr * 100U;
    if (c->stopdrift_en && g->speed_kmh < 2.0f && dist_mm < threshold_mm)
        return;
    if (dist_mm > 500U && dist_mm < 1000000U) {
        uint32_t earned_mm = dist_mm + s_remainder_mm;
        uint32_t delta_m = earned_mm / 1000U;
        s_remainder_mm = (uint16_t)(earned_mm % 1000U);
        if (delta_m != 0U) {
            cfg_add_mileage(delta_m);
            DBG_PRINTF_VERBOSE("[MILE] +%um total=%um\r\n",
                       (unsigned)delta_m, (unsigned)c->mileage_m);
        }
    }

    s_last_lat_e7 = g->lat_e7;
    s_last_lon_e7 = g->lon_e7;
}

static bool mileage_flush_at(uint32_t now_ms)
{
    if (!cfg_mileage_dirty()) {
        s_persist_schedule_armed = false;
        s_retry_backoff_active = false;
        return true;
    }
    if (cfg_flush_mileage()) {
        s_persist_schedule_armed = false;
        s_retry_backoff_active = false;
        return true;
    }
    s_persist_schedule_armed = true;
    s_retry_backoff_active = true;
    s_persist_due_ms = now_ms + MILEAGE_RETRY_BACKOFF_MS;
    dbg_printf("[MILE] persist failed; retry_after=%lu\r\n",
               (unsigned long)s_persist_due_ms);
    return false;
}

static void mileage_sync_persist_generation(void)
{
    uint32_t generation = cfg_persist_generation();
    if (generation == s_seen_persist_generation)
        return;
    s_seen_persist_generation = generation;
    s_persist_schedule_armed = false;
    s_retry_backoff_active = false;
}

void mileage_persist_process(uint32_t now_ms)
{
    mileage_sync_persist_generation();
    if (!cfg_mileage_dirty()) {
        s_persist_schedule_armed = false;
        s_retry_backoff_active = false;
        return;
    }
    if (!s_persist_schedule_armed) {
        s_persist_schedule_armed = true;
        s_retry_backoff_active = false;
        s_persist_due_ms = now_ms + MILEAGE_PERSIST_INTERVAL_MS;
        return;
    }
    if ((int32_t)(now_ms - s_persist_due_ms) >= 0)
        (void)mileage_flush_at(now_ms);
}

bool mileage_force_save(uint32_t now_ms)
{
    mileage_sync_persist_generation();
    if (!cfg_mileage_dirty()) {
        s_persist_schedule_armed = false;
        s_retry_backoff_active = false;
        return true;
    }
    if (s_retry_backoff_active &&
        (int32_t)(now_ms - s_persist_due_ms) < 0)
        return false;
    return mileage_flush_at(now_ms);
}
