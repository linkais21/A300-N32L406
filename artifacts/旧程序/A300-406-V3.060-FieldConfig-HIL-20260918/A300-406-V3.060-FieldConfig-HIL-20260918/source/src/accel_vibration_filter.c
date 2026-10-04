#include "accel_vibration_filter.h"

#include <stddef.h>

#define ACCEL_VIBRATION_BASELINE_SHIFT 3U

static uint32_t absolute_difference(int32_t value, int32_t baseline)
{
    int32_t difference = value - baseline;
    return (uint32_t)(difference < 0 ? -difference : difference);
}

void accel_vibration_filter_reset(accel_vibration_filter_t *filter)
{
    if (filter == NULL)
        return;
    filter->baseline_x = 0;
    filter->baseline_y = 0;
    filter->baseline_z = 0;
    filter->initialized = false;
}

bool accel_vibration_filter_step(accel_vibration_filter_t *filter,
                                 int16_t x, int16_t y, int16_t z,
                                 uint16_t threshold, uint16_t *motion)
{
    uint32_t dx;
    uint32_t dy;
    uint32_t dz;
    uint32_t maximum;

    if (motion != NULL)
        *motion = 0U;
    if (filter == NULL)
        return false;

    if (!filter->initialized) {
        filter->baseline_x = x;
        filter->baseline_y = y;
        filter->baseline_z = z;
        filter->initialized = true;
        return false;
    }

    dx = absolute_difference(x, filter->baseline_x);
    dy = absolute_difference(y, filter->baseline_y);
    dz = absolute_difference(z, filter->baseline_z);
    maximum = dx > dy ? (dx > dz ? dx : dz) : (dy > dz ? dy : dz);

    if (motion != NULL)
        *motion = (uint16_t)maximum;

    filter->baseline_x += ((int32_t)x - filter->baseline_x) >>
                          ACCEL_VIBRATION_BASELINE_SHIFT;
    filter->baseline_y += ((int32_t)y - filter->baseline_y) >>
                          ACCEL_VIBRATION_BASELINE_SHIFT;
    filter->baseline_z += ((int32_t)z - filter->baseline_z) >>
                          ACCEL_VIBRATION_BASELINE_SHIFT;

    return maximum > threshold;
}
