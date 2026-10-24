#ifndef ACCEL_VIBRATION_FILTER_H
#define ACCEL_VIBRATION_FILTER_H

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    int32_t baseline_x;
    int32_t baseline_y;
    int32_t baseline_z;
    bool initialized;
} accel_vibration_filter_t;

void accel_vibration_filter_reset(accel_vibration_filter_t *filter);
bool accel_vibration_filter_step(accel_vibration_filter_t *filter,
                                 int16_t x, int16_t y, int16_t z,
                                 uint16_t threshold, uint16_t *motion);

#endif
