#ifndef GEOFENCE_H
#define GEOFENCE_H
#include <stdint.h>
#include <stdbool.h>

#define GEOFENCE_MAX_ZONES    8
#define GEOFENCE_MAX_VERTICES 20

typedef struct {
    uint32_t zone_id;
    uint8_t  vertex_count;
    double   lat[GEOFENCE_MAX_VERTICES];
    double   lon[GEOFENCE_MAX_VERTICES];
    bool     active;
    bool     was_inside;        /* state from last check */
    uint8_t  alert_on;          /* 0=both 1=enter 2=exit */
} geofence_zone_t;

void geofence_init(void);
void geofence_add_zone(const geofence_zone_t *zone);
void geofence_remove_zone(uint32_t zone_id);
void geofence_process(void);    /* call from main loop */

/* JT808 0x8604 handler */
void geofence_handle_jt808(const uint8_t *body, uint16_t len, uint16_t sn);

#endif
