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
 * mileage.c — Haversine-based odometer + stop-drift filter + angle-change trigger
 *
 * Stop-drift filter:
 *   If reported speed < stopdrift_threshold (km/h) AND
 *   position change < stopdrift_radius (m), ignore the update.
 *   This prevents GPS noise from accumulating fake distance.
 *
 * Angle-change trigger:
 *   If heading changes by more than anglerep_angle degrees AND
 *   speed > anglerep_speed (km/h), force an immediate JT808 location report.
 */

#define EARTH_R_M  6371000.0   /* Earth radius in metres */

static double s_last_lat  = 0.0;
static double s_last_lon  = 0.0;
static float  s_last_hdg  = 0.0f;
static bool   s_has_first = false;

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

    double dist_m = haversine_m(s_last_lat, s_last_lon, g->lat, g->lon);

    /* Stop-drift filter */
    if (c->stopdrift_en) {
        float thr_m = (float)c->stopdrift_thr / 10.0f; /* thr in cm→m */
        if (g->speed_kmh < 2.0f && dist_m < thr_m)
            return;
    }

    /* Accumulate mileage */
    if (dist_m > 0.5 && dist_m < 1000.0) {  /* sanity: >0.5m, <1km per update */
        cfg_add_mileage((uint32_t)dist_m);
        dbg_printf("[MILE] +%um total=%um\r\n",
                   (unsigned)dist_m, (unsigned)c->mileage_m);
    }

    /* Angle-change trigger */
    if (c->anglerep_en && g->speed_kmh >= c->anglerep_speed) {
        float diff = fabsf(g->heading - s_last_hdg);
        if (diff > 180.0f) diff = 360.0f - diff;
        if (diff >= (float)c->anglerep_angle) {
            dbg_printf("[ANGLE] heading change %.1f deg, force report\r\n", diff);
            jt808_send_location();
            s_last_hdg = g->heading;
        }
    }

    s_last_lat = g->lat;
    s_last_lon = g->lon;
}
