#include "motion_corner.h"

#include <math.h>
#include <string.h>

#define DEFAULT_ENTER_ACCUM_DEG 30.0f
#define DEFAULT_EXIT_STABLE_DEG 0.5f
#define DEFAULT_CONFIRM_SAMPLES 2U
#define DEFAULT_EXIT_STABLE_SAMPLES 5U
#define DEFAULT_MAX_REPORTS 12U
#define DEFAULT_ACTIVE_MAX_MS 60000U
#define SHARP_STEP_DEG 12.0f

motion_corner_config_t motion_corner_default_config(void)
{
    motion_corner_config_t c;
    c.enter_accum_deg = DEFAULT_ENTER_ACCUM_DEG;
    c.exit_stable_deg = DEFAULT_EXIT_STABLE_DEG;
    c.confirm_samples = DEFAULT_CONFIRM_SAMPLES;
    c.exit_stable_samples = DEFAULT_EXIT_STABLE_SAMPLES;
    c.max_reports = DEFAULT_MAX_REPORTS;
    c.active_max_ms = DEFAULT_ACTIVE_MAX_MS;
    return c;
}

void motion_corner_init(motion_corner_ctx_t *ctx,
                        const motion_corner_config_t *config)
{
    if (ctx == NULL) return;
    memset(ctx, 0, sizeof(*ctx));
    ctx->config = config != NULL ? *config : motion_corner_default_config();
    ctx->state = MOTION_CORNER_STRAIGHT;
    ctx->previous_heading = 0.0f;
}

void motion_corner_reset(motion_corner_ctx_t *ctx)
{
    motion_corner_config_t config;
    if (ctx == NULL) return;
    config = ctx->config;
    memset(ctx, 0, sizeof(*ctx));
    ctx->config = config;
    ctx->state = MOTION_CORNER_STRAIGHT;
}

float motion_corner_heading_delta(float from_deg, float to_deg)
{
    float delta = to_deg - from_deg;
    if (delta > 180.0f) delta -= 360.0f;
    else if (delta < -180.0f) delta += 360.0f;
    return delta;
}

uint32_t motion_corner_interval_ms(float speed_kmh, bool sharp)
{
    if (sharp) return 1000U;
    if (speed_kmh < 30.0f) return 5000U;
    if (speed_kmh < 60.0f) return 3000U;
    return 2000U;
}

static void clear_motion(motion_corner_ctx_t *ctx, float heading)
{
    ctx->state = MOTION_CORNER_STRAIGHT;
    ctx->previous_heading = heading;
    ctx->have_heading = true;
    ctx->accumulated_deg = 0.0f;
    ctx->confirm_count = 0U;
    ctx->stable_count = 0U;
    ctx->turn_started_ms = 0U;
    ctx->last_report_ms = 0U;
    ctx->candidate_count = 0U;
    ctx->report_count = 0U;
}

static void enqueue_candidate(motion_corner_ctx_t *ctx,
                               const motion_corner_sample_t *sample,
                               bool sharp)
{
    uint32_t interval;
    uint32_t previous_ms;
    motion_corner_candidate_t *candidate;

    if (ctx->candidate_count >= MOTION_CORNER_CANDIDATE_CAPACITY) return;
    previous_ms = ctx->candidate_count == 0U ? ctx->last_report_ms :
                  ctx->candidates[ctx->candidate_count - 1U].sample.sample_ms;
    interval = motion_corner_interval_ms(sample->speed_kmh, sharp);
    if (previous_ms != 0U && sample->sample_ms - previous_ms < interval)
        return;
    candidate = &ctx->candidates[ctx->candidate_count++];
    candidate->sample = *sample;
    candidate->sharp = sharp;
}

motion_corner_event_t motion_corner_step(motion_corner_ctx_t *ctx,
                                         const motion_corner_sample_t *sample)
{
    motion_corner_event_t event = { false, MOTION_CORNER_REASON_NONE, false };
    float step;
    float abs_step;
    bool sharp;

    if (ctx != NULL && ctx->candidate_count != 0U &&
        (ctx->state == MOTION_CORNER_TURN_ACTIVE || ctx->report_count != 0U)) {
        event.report_due = true;
        event.reason = MOTION_CORNER_REASON_TURN_ACTIVE;
        return event;
    }
    if (ctx != NULL && sample != NULL && !sample->valid) {
        clear_motion(ctx, 0.0f);
        ctx->have_heading = false;
    }
    if (ctx == NULL || sample == NULL || !sample->valid ||
        !sample->heading_fresh || !isfinite(sample->heading_deg) ||
        sample->heading_deg < 0.0f || sample->heading_deg >= 360.0f ||
        !isfinite(sample->speed_kmh) || sample->speed_kmh < 0.0f)
        return event;

    if (!ctx->have_heading) {
        ctx->previous_heading = sample->heading_deg;
        ctx->have_heading = true;
        return event;
    }

    step = motion_corner_heading_delta(ctx->previous_heading,
                                       sample->heading_deg);
    abs_step = fabsf(step);
    sharp = abs_step >= SHARP_STEP_DEG;
    ctx->previous_heading = sample->heading_deg;

    if (ctx->state == MOTION_CORNER_TURN_EXIT) {
        if (abs_step > ctx->config.exit_stable_deg) {
            ctx->state = MOTION_CORNER_TURN_ACTIVE;
            ctx->stable_count = 0U;
        } else if (++ctx->stable_count >= ctx->config.exit_stable_samples) {
            clear_motion(ctx, sample->heading_deg);
            event.report_due = true;
            event.reason = MOTION_CORNER_REASON_TURN_EXIT;
            return event;
        }
        return event;
    }

    if (ctx->state == MOTION_CORNER_TURN_ACTIVE) {
        if (abs_step <= ctx->config.exit_stable_deg) {
            if (ctx->stable_count < UINT8_MAX) ++ctx->stable_count;
        } else {
            ctx->stable_count = 0U;
        }
        if (abs_step > ctx->config.exit_stable_deg)
            enqueue_candidate(ctx, sample, sharp);
        if (ctx->candidate_count > 0U) {
            event.report_due = true;
            event.reason = MOTION_CORNER_REASON_TURN_ACTIVE;
            event.sharp = sharp;
        }
        if (ctx->stable_count >= ctx->config.exit_stable_samples) {
            /* Capture the final stable sample as the exit report, then leave
             * the turn state immediately.  This avoids an empty EXIT event
             * followed by a second five-sample delay. */
            enqueue_candidate(ctx, sample, false);
            ctx->state = MOTION_CORNER_STRAIGHT;
            ctx->stable_count = 0U;
            ctx->accumulated_deg = 0.0f;
            ctx->confirm_count = 0U;
            ctx->turn_started_ms = 0U;
            event.report_due = ctx->candidate_count > 0U;
            event.reason = event.report_due ? MOTION_CORNER_REASON_TURN_EXIT :
                           MOTION_CORNER_REASON_NONE;
        }
        if ((ctx->config.max_reports != 0U &&
             ctx->report_count >= ctx->config.max_reports) ||
            (ctx->turn_started_ms != 0U &&
             sample->sample_ms - ctx->turn_started_ms >= ctx->config.active_max_ms)) {
            clear_motion(ctx, sample->heading_deg);
            event.report_due = false;
            event.reason = MOTION_CORNER_REASON_NONE;
        }
        return event;
    }

    /* Accumulate signed heading across a bounded observation window. Small
     * same-direction samples are a gentle bend, not a reason to erase it;
     * opposing jitter cancels instead of adding fictitious angle. */
    if (ctx->turn_started_ms == 0U ||
        sample->sample_ms - ctx->turn_started_ms >= ctx->config.active_max_ms) {
        ctx->accumulated_deg = 0.0f;
        ctx->confirm_count = 0U;
        ctx->candidate_count = 0U;
        ctx->turn_started_ms = sample->sample_ms;
    }
    ctx->accumulated_deg += step;
    if (step != 0.0f && ctx->confirm_count < UINT8_MAX) ++ctx->confirm_count;
    /* Opposing samples can cancel an unconfirmed turn. Re-evaluate the gate
     * instead of retaining a threshold crossing from an earlier sample. */
    ctx->state = fabsf(ctx->accumulated_deg) >= ctx->config.enter_accum_deg ?
                 MOTION_CORNER_TURN_ENTER : MOTION_CORNER_STRAIGHT;
    if (ctx->state == MOTION_CORNER_TURN_ENTER &&
        (ctx->confirm_count >= ctx->config.confirm_samples || sharp)) {
        ctx->state = MOTION_CORNER_TURN_ACTIVE;
        ctx->turn_started_ms = sample->sample_ms;
        ctx->stable_count = 0U;
        ctx->report_count = 0U;
        enqueue_candidate(ctx, sample, sharp);
        event.report_due = ctx->candidate_count > 0U;
        event.reason = event.report_due ? MOTION_CORNER_REASON_TURN_ENTER :
                       MOTION_CORNER_REASON_NONE;
        event.sharp = sharp;
    }
    return event;
}

motion_corner_state_t motion_corner_state(const motion_corner_ctx_t *ctx)
{
    return ctx == NULL ? MOTION_CORNER_STRAIGHT : ctx->state;
}

uint8_t motion_corner_pending_candidates(const motion_corner_ctx_t *ctx)
{
    return ctx == NULL ? 0U : ctx->candidate_count;
}

bool motion_corner_peek_candidate(const motion_corner_ctx_t *ctx,
                                  motion_corner_candidate_t *candidate)
{
    if (ctx == NULL || candidate == NULL || ctx->candidate_count == 0U)
        return false;
    *candidate = ctx->candidates[0];
    return true;
}

void motion_corner_consume_candidate(motion_corner_ctx_t *ctx)
{
    uint8_t i;
    if (ctx == NULL || ctx->candidate_count == 0U) return;
    ctx->last_report_ms = ctx->candidates[0].sample.sample_ms;
    if (ctx->report_count < UINT8_MAX) ++ctx->report_count;
    for (i = 1U; i < ctx->candidate_count; ++i)
        ctx->candidates[i - 1U] = ctx->candidates[i];
    --ctx->candidate_count;
    if (ctx->config.max_reports != 0U &&
        ctx->report_count >= ctx->config.max_reports)
        clear_motion(ctx, ctx->previous_heading);
}
