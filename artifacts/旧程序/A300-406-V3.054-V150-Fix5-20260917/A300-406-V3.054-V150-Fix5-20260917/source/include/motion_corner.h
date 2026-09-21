#ifndef MOTION_CORNER_H
#define MOTION_CORNER_H

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    MOTION_CORNER_STRAIGHT = 0,
    MOTION_CORNER_TURN_ENTER,
    MOTION_CORNER_TURN_ACTIVE,
    MOTION_CORNER_TURN_EXIT
} motion_corner_state_t;

typedef enum {
    MOTION_CORNER_REASON_NONE = 0,
    MOTION_CORNER_REASON_TURN_ENTER,
    MOTION_CORNER_REASON_TURN_ACTIVE,
    MOTION_CORNER_REASON_TURN_EXIT
} motion_corner_reason_t;

typedef struct {
    float heading_deg;
    float speed_kmh;
    uint32_t sample_ms;
    bool valid;
    bool heading_fresh;
} motion_corner_sample_t;

typedef struct {
    float enter_accum_deg;
    float meaningful_step_deg;
    float opposing_noise_deg;
    float exit_stable_deg;
    uint8_t confirm_samples;
    uint8_t exit_stable_samples;
    uint8_t max_reports;
    uint32_t active_max_ms;
} motion_corner_config_t;

typedef struct {
    motion_corner_sample_t sample;
    bool sharp;
} motion_corner_candidate_t;

typedef struct {
    bool report_due;
    motion_corner_reason_t reason;
    bool sharp;
} motion_corner_event_t;

#define MOTION_CORNER_CANDIDATE_CAPACITY 3U

typedef struct {
    motion_corner_config_t config;
    motion_corner_state_t state;
    float previous_heading;
    int8_t direction;
    float accumulated_deg;
    uint8_t confirm_count;
    uint8_t stable_count;
    uint8_t report_count;
    uint32_t turn_started_ms;
    uint32_t last_report_ms;
    bool have_heading;
    motion_corner_candidate_t candidates[MOTION_CORNER_CANDIDATE_CAPACITY];
    uint8_t candidate_count;
} motion_corner_ctx_t;

motion_corner_config_t motion_corner_default_config(void);
void motion_corner_init(motion_corner_ctx_t *ctx,
                        const motion_corner_config_t *config);
void motion_corner_reset(motion_corner_ctx_t *ctx);
motion_corner_event_t motion_corner_step(motion_corner_ctx_t *ctx,
                                         const motion_corner_sample_t *sample);
motion_corner_state_t motion_corner_state(const motion_corner_ctx_t *ctx);
float motion_corner_heading_delta(float from_deg, float to_deg);
uint32_t motion_corner_interval_ms(float speed_kmh, bool sharp);
uint8_t motion_corner_pending_candidates(const motion_corner_ctx_t *ctx);
bool motion_corner_peek_candidate(const motion_corner_ctx_t *ctx,
                                  motion_corner_candidate_t *candidate);
void motion_corner_consume_candidate(motion_corner_ctx_t *ctx);

#endif
