#include "gps.h"
#include "jt808.h"
#include "flash_config.h"
#include "hw_init.h"
#include "debug_uart.h"
#include "n32l40x.h"
#include <math.h>
#include <string.h>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

/*
 * mileage.c — Haversine-based odometer, stop-drift filter and persistence
 *
 * Stop-drift filter:
 *   When enabled, speed < 2.0 km/h AND distance from the last accepted
 *   position < stopdrift_thr / 10.0 metres rejects the update.
 *   Default raw 50 therefore means 5 m in this implementation.
 *   The external protocol unit is unconfirmed; preserve stored values and
 *   this conversion until the protocol/configuration contract is verified.
 */

#define EARTH_R_M  6371000.0   /* Earth radius in metres */

static double s_last_lat  = 0.0;
static double s_last_lon  = 0.0;
static float  s_last_hdg  = 0.0f;
static bool   s_has_first = false;
#define MILEAGE_PERSIST_INTERVAL_MS (600000UL)
#define MILEAGE_RETRY_BACKOFF_MS    (30000UL)
static bool s_persist_schedule_armed;
static bool s_retry_backoff_active;
static uint32_t s_persist_due_ms;
static uint32_t s_seen_persist_generation;

/* ── Haversine distance (metres) ─────────────────────────────────────────── */
static double haversine_m(double lat1, double lon1, double lat2, double lon2)
{
    double dlat = (lat2 - lat1) * M_PI / 180.0;
    double dlon = (lon2 - lon1) * M_PI / 180.0;
    double a = sin(dlat/2)*sin(dlat/2)
             + cos(lat1*M_PI/180.0)*cos(lat2*M_PI/180.0)
             * sin(dlon/2)*sin(dlon/2);
    double c = 2.0 * atan2(sqrt(a), sqrt(1.0 - a));
    return EARTH_R_M * c;
}

void mileage_update(void)
{
    const gps_data_t *g = gps_get_data();
    if (!g->valid) return;

    device_config_t *c = cfg_get();

    if (!s_has_first) {
        s_last_lat  = g->lat;
        s_last_lon  = g->lon;
        s_last_hdg  = g->heading;
        s_has_first = true;
        return;
    }

    /* The main loop may run several times before GPS publishes a new fix.
     * Reusing the exact same coordinates must not pay for haversine/libm
     * again or re-evaluate the same sample. */
    if (g->lat == s_last_lat && g->lon == s_last_lon)
        return;

    double dist_m = haversine_m(s_last_lat, s_last_lon, g->lat, g->lon);

    /* Stop-drift filter */
    if (c->stopdrift_en) {
        float thr_m = (float)c->stopdrift_thr / 10.0f; /* Existing raw / 10 scaling to metres; not cm-to-m. */
        if (g->speed_kmh < 2.0f && dist_m < thr_m)
            return;
    }

    /* Accumulate mileage */
    if (dist_m > 0.5 && dist_m < 1000.0) {  /* sanity: >0.5m, <1km per update */
        cfg_add_mileage((uint32_t)dist_m);
        dbg_printf("[MILE] +%um total=%um\r\n",
                   (unsigned)dist_m, (unsigned)c->mileage_m);
    }

    s_last_lat = g->lat;
    s_last_lon = g->lon;
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
