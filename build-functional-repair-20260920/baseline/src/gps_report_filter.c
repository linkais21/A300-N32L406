#include "gps_report_filter.h"
#include "i2c_accel.h"
#include "flash_config.h"
#include <math.h>
#include <string.h>

#define REPORT_WINDOW_COUNT      5u
#define REPORT_ACCEL_PERIOD_MS   200u
#define REPORT_ACCEL_GAP_MS      1000u
#define REPORT_FIX_MAX_AGE_MS    3000u
#define REPORT_MOVE_FIXES        3u
#define REPORT_ACCEL_LSB_PER_G   1024u

typedef enum {
    REPORT_UNKNOWN = 0,
    REPORT_MOVING,
    REPORT_CANDIDATE,
    REPORT_LOCKED
} report_state_t;

/* L406 field trial: observed stationary windows reached 100 LSB (~98 mg).
 * Keep hysteresis and speed release; these thresholds require moving HIL. */
static const gps_report_filter_config_t s_config = {
    1.0f, 2.0f, 120u, 180u, 30000u
};
static struct {
    uint8_t state; /* report_state_t; compact to avoid alignment padding */
    uint8_t blockers;
    int16_t acceleration[REPORT_WINDOW_COUNT][3];
    /* Candidate samples and locked anchor have disjoint lifetimes.
     * 1e-7 degree samples preserve centimetre precision without 80 B doubles. */
    union {
        struct { int32_t lat[REPORT_WINDOW_COUNT], lon[REPORT_WINDOW_COUNT]; } fixes;
        struct { double lat, lon; } anchor;
    } position;
    uint32_t last_poll_ms, last_rmc_ms, candidate_ms;
    uint8_t fix_count, fix_next, move_count;
    /* Five-entry ring and evidence flags fit in one byte; no persisted ABI. */
    uint8_t accel_count : 3;
    uint8_t accel_next : 3;
    uint8_t have_poll : 1;
    uint8_t have_rmc : 1;
} s_report;

static bool report_enabled(void)
{
    const device_config_t *config = cfg_get();
    return config != NULL && config->stopdrift_en != 0u && gps_is_enabled();
}

static bool report_fix_fresh(const gps_data_t *gps, uint32_t now_ms)
{
    return (gps != NULL && gps->valid && gps_is_valid()) &&
           isfinite(gps->lat) && isfinite(gps->lon) &&
           gps->lat >= -90.0 && gps->lat <= 90.0 &&
           gps->lon >= -180.0 && gps->lon <= 180.0 &&
           isfinite(gps->speed_kmh) && gps->speed_kmh >= 0.0f &&
           now_ms - gps->last_update_ms <= REPORT_FIX_MAX_AGE_MS &&
           now_ms - gps->heading_update_ms <= REPORT_FIX_MAX_AGE_MS;
}

static void clear_candidate(report_state_t state)
{
    s_report.state = state;
    s_report.fix_count = 0u;
    s_report.fix_next = 0u;
    s_report.candidate_ms = 0u;
}

/* Retain poll deadline after failed reads: recovery must not busy-poll I2C. */
static void invalidate_evidence(void)
{
    clear_candidate(REPORT_UNKNOWN);
    s_report.accel_count = 0u;
    s_report.accel_next = 0u;
    s_report.move_count = 0u;
    s_report.have_rmc = false;
}

void gps_report_filter_reset(void)
{
    memset(&s_report, 0, sizeof(s_report));
}

void gps_report_filter_init(void)
{
    gps_report_filter_reset();
}

static bool acceleration_legal(const accel_data_t *a)
{
    /* Existing driver's signed >>4 representation has range -2048..2047.
     * Reject railed/zero samples; no-motion must not mean an unplugged sensor. */
    return a->x > -2048 && a->x < 2047 &&
           a->y > -2048 && a->y < 2047 &&
           a->z > -2048 && a->z < 2047 &&
           (a->x != 0 || a->y != 0 || a->z != 0);
}

static uint32_t acceleration_span(void)
{
    uint32_t span = 0u;
    for (uint8_t axis = 0u; axis < 3u; ++axis) {
        int16_t low = s_report.acceleration[0][axis], high = low;
        for (uint8_t i = 1u; i < s_report.accel_count; ++i) {
            int16_t value = s_report.acceleration[i][axis];
            if (value < low) low = value;
            if (value > high) high = value;
        }
        uint32_t delta = (uint32_t)((int32_t)high - (int32_t)low);
        if (delta > span) span = delta;
    }
    return span;
}

void gps_report_filter_get_diag(gps_report_filter_diag_t *out, uint32_t now_ms)
{
    if (out == NULL) return;
    out->state = s_report.state;
    out->blockers = s_report.blockers;
    out->span_lsb = s_report.accel_count ? (uint16_t)acceleration_span() : 0u;
    out->candidate_ms = s_report.state == REPORT_CANDIDATE ?
                        now_ms - s_report.candidate_ms : 0u;
}

/* Shared by latitude/longitude; inlining duplicates the 64-bit arithmetic. */
static __attribute__((noinline)) double trimmed_mean(const int32_t *values)
{
    const int64_t half_turn = 1800000000LL;
    int64_t origin = values[0];
    int64_t sum = origin, low = origin, high = origin;
    for (uint8_t i = 1u; i < REPORT_WINDOW_COUNT; i++) {
        int64_t value = values[i];
        /* Longitude is circular: unwrap around the first fix so stationary
         * samples at +180/-180 cannot average into a different continent.
         * Valid latitude differences never exceed 180 degrees, so the same
         * operation is an identity for latitude and needs no separate flag. */
        if (value - origin > half_turn) value -= 2 * half_turn;
        else if (value - origin < -half_turn) value += 2 * half_turn;
        sum += value;
        if (value < low) low = value;
        if (value > high) high = value;
    }
    /* At most five unwrapped e7 samples: int32 could overflow.
     * Normalize the retained sum before a single double conversion. */
    sum -= low + high;
    if (sum > 3 * half_turn) sum -= 6 * half_turn;
    else if (sum < -3 * half_turn) sum += 6 * half_turn;
    return (double)sum / 30000000.0;
}

void gps_report_filter_process(uint32_t now_ms)
{
    const gps_data_t *gps = gps_get_data();
    if (!report_enabled()) {
        s_report.blockers |= GPS_REPORT_BLOCK_DISABLED;
        invalidate_evidence();
        return;
    }
    if (!report_fix_fresh(gps, now_ms)) {
        s_report.blockers |= GPS_REPORT_BLOCK_FIX;
        invalidate_evidence();
        return;
    }
    if (s_report.have_poll &&
        now_ms - s_report.last_poll_ms > REPORT_ACCEL_GAP_MS) {
        s_report.blockers |= GPS_REPORT_BLOCK_GAP;
        invalidate_evidence();
    }
    if (!s_report.have_poll ||
        now_ms - s_report.last_poll_ms >= REPORT_ACCEL_PERIOD_MS) {
        accel_data_t a;
        s_report.last_poll_ms = now_ms;
        s_report.have_poll = true;
        if (!i2c_accel_read(&a) || !acceleration_legal(&a)) {
            s_report.blockers |= GPS_REPORT_BLOCK_SENSOR;
            invalidate_evidence();
            return;
        }
        s_report.acceleration[s_report.accel_next][0] = a.x;
        s_report.acceleration[s_report.accel_next][1] = a.y;
        s_report.acceleration[s_report.accel_next][2] = a.z;
        s_report.accel_next = (uint8_t)((s_report.accel_next + 1u) % REPORT_WINDOW_COUNT);
        if (s_report.accel_count < REPORT_WINDOW_COUNT) s_report.accel_count++;
    }
    if (s_report.accel_count == 0u) return;

    bool new_rmc = !s_report.have_rmc || gps->heading_update_ms != s_report.last_rmc_ms;
    if (new_rmc) {
        if (s_report.have_rmc &&
            gps->heading_update_ms - s_report.last_rmc_ms > REPORT_FIX_MAX_AGE_MS) {
            s_report.blockers |= GPS_REPORT_BLOCK_RMC_GAP;
            s_report.move_count = 0u;
            clear_candidate(REPORT_UNKNOWN);
        }
        s_report.have_rmc = true;
        s_report.last_rmc_ms = gps->heading_update_ms;
        if (gps->speed_kmh >= s_config.move_speed_kmh) {
            if (s_report.move_count < REPORT_MOVE_FIXES) s_report.move_count++;
        } else {
            s_report.move_count = 0u;
        }
    }

    /* Exact integer mg comparison; 4094 LSB *1000 fits uint32.
     * Check partial window too so a new jolt releases within one poll. */
    uint32_t span_milli_lsb = acceleration_span() * 1000u;
    if (span_milli_lsb >= (uint32_t)s_config.move_accel_mg * REPORT_ACCEL_LSB_PER_G ||
        s_report.move_count >= REPORT_MOVE_FIXES) {
        if (span_milli_lsb >= (uint32_t)s_config.move_accel_mg * REPORT_ACCEL_LSB_PER_G)
            s_report.blockers |= GPS_REPORT_BLOCK_ACCEL;
        if (s_report.move_count >= REPORT_MOVE_FIXES)
            s_report.blockers |= GPS_REPORT_BLOCK_SPEED;
        clear_candidate(REPORT_MOVING);
        return;
    }
    if (s_report.state == REPORT_LOCKED) return;
    if (s_report.accel_count < REPORT_WINDOW_COUNT ||
        span_milli_lsb > (uint32_t)s_config.stable_accel_mg * REPORT_ACCEL_LSB_PER_G ||
        gps->speed_kmh > s_config.stop_speed_kmh) {
        if (span_milli_lsb > (uint32_t)s_config.stable_accel_mg * REPORT_ACCEL_LSB_PER_G)
            s_report.blockers |= GPS_REPORT_BLOCK_UNSTABLE;
        if (gps->speed_kmh > s_config.stop_speed_kmh)
            s_report.blockers |= GPS_REPORT_BLOCK_SPEED;
        clear_candidate(REPORT_MOVING);
        return;
    }
    if (s_report.state != REPORT_CANDIDATE) {
        clear_candidate(REPORT_CANDIDATE);
        s_report.candidate_ms = now_ms;
    }
    if (new_rmc) {
        s_report.position.fixes.lat[s_report.fix_next] = (int32_t)(gps->lat * 10000000.0);
        s_report.position.fixes.lon[s_report.fix_next] = (int32_t)(gps->lon * 10000000.0);
        s_report.fix_next = (uint8_t)((s_report.fix_next + 1u) % REPORT_WINDOW_COUNT);
        if (s_report.fix_count < REPORT_WINDOW_COUNT) s_report.fix_count++;
    }
    if (s_report.fix_count == REPORT_WINDOW_COUNT &&
        now_ms - s_report.candidate_ms >= s_config.stationary_ms) {
        double lat = trimmed_mean(s_report.position.fixes.lat);
        double lon = trimmed_mean(s_report.position.fixes.lon);
        s_report.position.anchor.lat = lat;
        s_report.position.anchor.lon = lon;
        s_report.state = REPORT_LOCKED;
    }
}

bool gps_report_filter_copy(const gps_data_t *raw, gps_data_t *out, uint32_t now_ms)
{
    if (raw == NULL || out == NULL || raw == out) return false;
    *out = *raw;
    if (!report_enabled() || s_report.state != REPORT_LOCKED ||
        !report_fix_fresh(raw, now_ms) || !s_report.have_poll ||
        now_ms - s_report.last_poll_ms > REPORT_ACCEL_GAP_MS) return false;
    out->lat = s_report.position.anchor.lat;
    out->lon = s_report.position.anchor.lon;
    out->speed_kmh = 0.0f;
    out->heading = 0.0f;
    return true;
}
