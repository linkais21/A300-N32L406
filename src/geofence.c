#include "geofence.h"
#include "gps.h"
#include "jt808.h"
#include "debug_uart.h"
#include <string.h>
#include <math.h>

static geofence_zone_t s_zones[GEOFENCE_MAX_ZONES];
static uint8_t s_zone_count = 0;

/* ── Ray-casting point-in-polygon ────────────────────────────────────────── */
static bool point_in_polygon(double lat, double lon,
                              const double *vlat, const double *vlon,
                              uint8_t n)
{
    bool inside = false;
    for (uint8_t i = 0, j = n - 1; i < n; j = i++) {
        if (((vlon[i] > lon) != (vlon[j] > lon)) &&
            (lat < (vlat[j] - vlat[i]) * (lon - vlon[i]) /
                   (vlon[j] - vlon[i]) + vlat[i]))
            inside = !inside;
    }
    return inside;
}

/* ── Parse big-endian double (IEEE 754, 8 bytes) ─────────────────────────── */
static double parse_jt808_coord(const uint8_t *p)
{
    /* JT808 sends latitude/longitude as int32 × 1e-6 degrees */
    int32_t raw = ((int32_t)p[0] << 24) | ((int32_t)p[1] << 16) |
                  ((int32_t)p[2] << 8)  |  (int32_t)p[3];
    return raw / 1e6;
}

void geofence_init(void)
{
    memset(s_zones, 0, sizeof(s_zones));
    s_zone_count = 0;
}

void geofence_add_zone(const geofence_zone_t *zone)
{
    if (s_zone_count >= GEOFENCE_MAX_ZONES) return;
    /* Replace existing zone with same ID */
    for (uint8_t i = 0; i < s_zone_count; i++) {
        if (s_zones[i].zone_id == zone->zone_id) {
            s_zones[i] = *zone;
            return;
        }
    }
    s_zones[s_zone_count++] = *zone;
}

void geofence_remove_zone(uint32_t zone_id)
{
    for (uint8_t i = 0; i < s_zone_count; i++) {
        if (s_zones[i].zone_id == zone_id) {
            /* Shift remaining zones down */
            memmove(&s_zones[i], &s_zones[i+1],
                    (s_zone_count - i - 1) * sizeof(geofence_zone_t));
            s_zone_count--;
            return;
        }
    }
}

void geofence_process(void)
{
    const gps_data_t *g = gps_get_data();
    if (!g->valid) return;

    for (uint8_t i = 0; i < s_zone_count; i++) {
        geofence_zone_t *z = &s_zones[i];
        if (!z->active) continue;

        bool inside = point_in_polygon(g->lat, g->lon,
                                       z->lat, z->lon, z->vertex_count);
        if (inside != z->was_inside) {
            bool entered = inside;
            dbg_printf("[GEO] zone %u: %s\r\n",
                       (unsigned)z->zone_id, entered ? "ENTER" : "EXIT");

            /* Trigger JT808 location report with geofence alarm */
            if ((z->alert_on == 0) ||
                (z->alert_on == 1 && entered) ||
                (z->alert_on == 2 && !entered)) {
                /* Use alarm bit 8 = area entry/exit (JT808 standard) */
                jt808_trigger_alarm(1u << 8);
                jt808_send_location();
            }
            z->was_inside = inside;
        }
    }
}

/* ── JT808 0x8604 set polygon area ──────────────────────────────────────── */
void geofence_handle_jt808(const uint8_t *body, uint16_t len, uint16_t sn)
{
    if (len < 10) goto done;

    uint16_t pos = 0;
    uint8_t  action      = body[pos++];   /* 0=update 1=append 2=delete */
    uint8_t  zone_count  = body[pos++];

    for (uint8_t z = 0; z < zone_count && pos + 8 < len; z++) {
        geofence_zone_t zone;
        memset(&zone, 0, sizeof(zone));

        zone.zone_id = ((uint32_t)body[pos] << 24) | ((uint32_t)body[pos+1] << 16) |
                       ((uint32_t)body[pos+2] << 8) |  (uint32_t)body[pos+3];
        pos += 4;
        zone.active    = (body[pos] & 1) ? true : false;
        zone.alert_on  = (body[pos] >> 1) & 0x03;
        pos += 2;   /* attr(1) + reserved(1) */

        if (action == 2) {   /* delete */
            geofence_remove_zone(zone.zone_id);
            continue;
        }

        /* Skip start/end time (8 bytes) and max/min speed (4 bytes) */
        pos += 12;
        if (pos + 2 > len) break;

        uint16_t vertex_count = ((uint16_t)body[pos] << 8) | body[pos+1];
        pos += 2;
        if (vertex_count > GEOFENCE_MAX_VERTICES) vertex_count = GEOFENCE_MAX_VERTICES;

        zone.vertex_count = (uint8_t)vertex_count;
        for (uint8_t v = 0; v < vertex_count && pos + 8 <= len; v++) {
            zone.lat[v] = parse_jt808_coord(&body[pos]);     pos += 4;
            zone.lon[v] = parse_jt808_coord(&body[pos]);     pos += 4;
        }
        zone.was_inside = false;
        geofence_add_zone(&zone);
    }
done:
    jt808_send_general_resp(sn, MSG_SET_POLYGON_AREA, 0);
    dbg_printf("[GEO] 0x8604 zone update done\r\n");
}
