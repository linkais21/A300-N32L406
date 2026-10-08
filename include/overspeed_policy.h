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

void overspeed_policy_init(overspeed_policy_t *policy);
bool overspeed_policy_step(overspeed_policy_t *policy, uint32_t now_ms,
                           bool realtime, bool gps_valid, float speed_kmh,
                           uint16_t limit_kmh, uint32_t duration_s);

#endif
