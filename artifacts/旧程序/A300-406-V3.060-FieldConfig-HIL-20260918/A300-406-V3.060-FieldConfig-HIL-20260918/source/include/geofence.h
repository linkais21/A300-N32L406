#ifndef GEOFENCE_H
#define GEOFENCE_H
#include <stdint.h>
/* The protocol boundary remains so 0x8604 can be rejected safely. */
void geofence_init(void);
void geofence_process(void);
void geofence_handle_jt808(const uint8_t *body, uint16_t len, uint16_t sn);
#endif
