#ifndef BLIND_ZONE_H
#define BLIND_ZONE_H

#include <stdbool.h>
#include <stdint.h>

#define BLIND_ZONE_LOCATION_MAX       40U
#define BLIND_ZONE_LOGICAL_CAPACITY   10000UL
#define BLIND_ZONE_PHYSICAL_SLOTS     10240UL

typedef enum {
    BLIND_ZONE_OK = 0,
    BLIND_ZONE_BUSY,
    BLIND_ZONE_INVALID,
    BLIND_ZONE_IO_ERROR,
} blind_zone_result_t;

typedef struct {
    uint8_t length;
    uint8_t location[BLIND_ZONE_LOCATION_MAX];
} blind_zone_record_t;

bool blind_zone_init(void);
void blind_zone_recovery_process(void);
bool blind_zone_ready(void);
blind_zone_result_t blind_zone_append(const blind_zone_record_t *record);
uint8_t blind_zone_peek(blind_zone_record_t *records, uint8_t capacity,
                        uint32_t *first_sequence);
blind_zone_result_t blind_zone_consume(uint32_t first_sequence, uint8_t count);

#endif
