#include "gps.h"
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
/* Bounded double-precision distance for mileage policy, not a
 * general navigation API. Valid geographic coordinates are required.
 * sin polynomial on [-pi/2, pi/2]: Taylor degree 19, exact-arithmetic omitted
 * term <= (pi/2)^21/21! < 2.6e-16. IEEE rounding is assessed separately.
 */
static double mileage_trial_sin(double x)
{
    double z = x * x;
    double p = -1.0 / 121645100408832000.0;
    p =  1.0 / 355687428096000.0 + z * p;
    p = -1.0 / 1307674368000.0 + z * p;
    p =  1.0 / 6227020800.0 + z * p;
    p = -1.0 / 39916800.0 + z * p;
    p =  1.0 / 362880.0 + z * p;
    p = -1.0 / 5040.0 + z * p;
    p =  1.0 / 120.0 + z * p;
    p = -1.0 / 6.0 + z * p;
    return x + x * z * p;
}

static double haversine_m(double lat1, double lon1, double lat2, double lon2)
{
    if (!(lat1 >= -90.0 && lat1 <= 90.0 && lat2 >= -90.0 && lat2 <= 90.0 &&
          lon1 >= -180.0 && lon1 <= 180.0 && lon2 >= -180.0 && lon2 <= 180.0))
        return NAN;
    double delta_lon = lon2 - lon1;
    if (delta_lon > 180.0) delta_lon -= 360.0;
    else if (delta_lon < -180.0) delta_lon += 360.0;
    double s_lat = mileage_trial_sin((lat2 - lat1) * (M_PI / 360.0));
    double s_lon = mileage_trial_sin(delta_lon * (M_PI / 360.0));
    double c1 = mileage_trial_sin((90.0 - fabs(lat1)) * (M_PI / 180.0));
    double c2 = mileage_trial_sin((90.0 - fabs(lat2)) * (M_PI / 180.0));
    double a = s_lat * s_lat + c1 * c2 * s_lon * s_lon;
    /* All distances >=8192 m reject mileage and exceed the maximum existing
     * uint16 stopdrift threshold /10 (6553.5 m). Their exact value is unused.
     * This cutoff must be revisited if those production contracts change. */
    if (a >= (8192.0 / (2.0 * EARTH_R_M)) * (8192.0 / (2.0 * EARTH_R_M)))
        return 8192.0;
    if (a <= 0.0) return 0.0;
    double root = (double)sqrtf((float)a);
    if (root == 0.0) return 0.0; /* sub-femtometre float underflow */
    root = 0.5 * (root + a / root);
    root = 0.5 * (root + a / root);
    /* asin(root) through root^5; cutoff bounds root < 0.000643.
     * The next term contributes < 3e-17 metres in exact arithmetic. */
    return 2.0 * EARTH_R_M * root * (1.0 + a * (1.0 / 6.0 + a * (3.0 / 40.0)));
}


void mileage_update(void)
{
    const gps_data_t *g = gps_get_data();
    if (!g->valid ||
        !(fabs(g->lat) <= 90.0 &&
          fabs(g->lon) <= 180.0)) return;

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

    /* Mileage policy: nearest millimetre, positive halfway up. */
    if (!isfinite(dist_m) || dist_m < 0.0) return;
    if (dist_m > 8192.0) dist_m = 8192.0;
    uint32_t dist_mm = (uint32_t)(dist_m * 1000.0 + 0.5);
    uint32_t threshold_mm = (uint32_t)c->stopdrift_thr * 100U;
    if (c->stopdrift_en && g->speed_kmh < 2.0f && dist_mm < threshold_mm)
        return;
    if (dist_mm > 500U && dist_mm < 1000000U) {
        uint32_t delta_m = dist_mm / 1000U;
        cfg_add_mileage(delta_m);
        DBG_PRINTF_VERBOSE("[MILE] +%um total=%um\r\n",
                   (unsigned)delta_m, (unsigned)c->mileage_m);
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
