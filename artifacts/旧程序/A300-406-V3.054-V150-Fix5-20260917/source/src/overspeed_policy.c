#include "overspeed_policy.h"

#include <stddef.h>

void overspeed_policy_init(overspeed_policy_t *policy)
{
    if (policy == NULL) return;
    policy->above_since_ms = 0U;
    policy->last_alarm_ms = 0U;
    policy->tracking = false;
    policy->fired_in_episode = false;
    policy->last_alarm_valid = false;
}

bool overspeed_policy_step(overspeed_policy_t *policy, uint32_t now_ms,
                           bool realtime, bool gps_valid, float speed_kmh,
                           uint16_t limit_kmh)
{
    if (policy == NULL) return false;
    if (!realtime || !gps_valid || !(speed_kmh >= 0.0f) ||
        limit_kmh < 20U || limit_kmh > 200U ||
        !(speed_kmh > (float)limit_kmh)) {
        policy->tracking = false;
        policy->fired_in_episode = false;
        return false;
    }
    if (!policy->tracking) {
        policy->tracking = true;
        policy->above_since_ms = now_ms;
        policy->fired_in_episode = false;
        return false;
    }
    if (policy->fired_in_episode ||
        (uint32_t)(now_ms - policy->above_since_ms) < OVERSPEED_PERSIST_MS ||
        (policy->last_alarm_valid &&
         (uint32_t)(now_ms - policy->last_alarm_ms) < OVERSPEED_COOLDOWN_MS)) {
        return false;
    }
    policy->fired_in_episode = true;
    policy->last_alarm_valid = true;
    policy->last_alarm_ms = now_ms;
    return true;
}
