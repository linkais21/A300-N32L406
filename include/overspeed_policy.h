#ifndef OVERSPEED_POLICY_H
#define OVERSPEED_POLICY_H

#include <stdbool.h>
#include <stdint.h>

#define OVERSPEED_COOLDOWN_MS 300000U

typedef struct {
    uint32_t above_since_ms;
    uint32_t last_alarm_ms;
    bool tracking;
    bool fired_in_episode;
    bool last_alarm_valid;
} overspeed_policy_t;

/* JT808 bit13 is a level, independent of the timed overspeed alarm (bit1).
 * Clamp subtraction at zero for the complete WORD range; stationary and
 * non-finite/out-of-wire-range speeds cannot raise a warning. */
static inline bool overspeed_warning_active(bool enabled, bool realtime,
                                            bool gps_valid, float speed_kmh,
                                            uint16_t limit_kmh,
                                            uint16_t delta_x10)
{
    uint32_t limit_x10 = (uint32_t)limit_kmh * 10U;
    uint32_t threshold = delta_x10 < limit_x10 ? limit_x10 - delta_x10 : 0U;
    return enabled && realtime && gps_valid && limit_kmh >= 20U &&
           limit_kmh <= 200U && speed_kmh > 0.0f && speed_kmh <= 6553.5f &&
           speed_kmh * 10.0f >= (float)threshold;
}

void overspeed_policy_init(overspeed_policy_t *policy);
bool overspeed_policy_step(overspeed_policy_t *policy, uint32_t now_ms,
                           bool realtime, bool gps_valid, float speed_kmh,
                           uint16_t limit_kmh, uint32_t duration_s);

#endif
