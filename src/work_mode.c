#include "work_mode.h"

#define WORK_MODE_ACTION_QUEUE_CAPACITY 8U
#define WORK_MODE_VIBRATION_SAMPLE_MS 200U
#define WORK_MODE_VIBRATION_MISS_TOLERANCE 2U
#define WORK_MODE_VIBRATION_MAX_GAP_MS 1000U
#define WORK_MODE_MS_PER_SECOND 1000U
#define WORK_MODE_MAX_SAFE_INTERVAL_S 0x7fffffffUL
#define WORK_MODE_MAX_VIBRATION_CONFIRM_S \
    (WORK_MODE_MAX_SAFE_INTERVAL_S / WORK_MODE_MS_PER_SECOND)
#define WORK_MODE_PENDING_ACTION_CAPACITY 8U

typedef struct {
    work_mode_action_t action;
    uint32_t generation;
    bool mode_entry;
} work_mode_queued_action_t;

typedef struct {
    work_mode_config_t config;
    work_mode_state_t state;
    bool logical_acc;
    bool previous_acc_high;
    uint32_t boot_monitor_started_s;
    uint32_t stationary_since_s;
    uint32_t moving_deadline_s;
    uint32_t stopped_deadline_s;
    uint32_t heartbeat_deadline_s;
    uint32_t vibration_hits;
    uint32_t vibration_miss_count;
    uint32_t vibration_started_ms;
    uint32_t vibration_last_hit_ms;
    uint32_t mode_generation;
    work_mode_queued_action_t actions[WORK_MODE_ACTION_QUEUE_CAPACITY];
    work_mode_queued_action_t pending_actions[WORK_MODE_PENDING_ACTION_CAPACITY];
    uint8_t action_head;
    uint8_t action_count;
    uint8_t pending_count;
} work_mode_context_t;

static work_mode_context_t g_work_mode;
static volatile uint32_t s_pending_alarm_bits;
static uint32_t s_acc_sample;

#define ACC_SAMPLE_VALID_MASK 0x80000000UL
#define ACC_SAMPLE_HIGH_MASK  0x40000000UL
#define ACC_SAMPLE_TIME_MASK  0x3fffffffUL

void work_mode_acc_sample(bool raw_high, uint32_t now_ms)
{
    /* A zero timestamp denotes legacy second-resolution callers; preserve
     * their immediate edge semantics for host policy tests and boot init. */
    s_acc_sample = now_ms == 0U ? 0U :
                   (ACC_SAMPLE_VALID_MASK | (raw_high ? ACC_SAMPLE_HIGH_MASK : 0U) |
                    (now_ms & ACC_SAMPLE_TIME_MASK));
}

static bool deadline_reached(uint32_t now_s, uint32_t deadline_s)
{
    return (int32_t)(now_s - deadline_s) >= 0;
}

static uint32_t interval_or_safe(uint32_t interval_s)
{
    if (interval_s == 0U) {
        return 1U;
    }
    if (interval_s > WORK_MODE_MAX_SAFE_INTERVAL_S) {
        return WORK_MODE_MAX_SAFE_INTERVAL_S;
    }
    return interval_s;
}

static uint32_t vibration_samples_required(void)
{
    uint32_t confirm_s = g_work_mode.config.vibration_confirm_s;
    uint32_t milliseconds;
    uint32_t samples;

    if (confirm_s > WORK_MODE_MAX_VIBRATION_CONFIRM_S) {
        confirm_s = WORK_MODE_MAX_VIBRATION_CONFIRM_S;
    }
    milliseconds = confirm_s * WORK_MODE_MS_PER_SECOND;
    samples = milliseconds / WORK_MODE_VIBRATION_SAMPLE_MS;
    if ((milliseconds % WORK_MODE_VIBRATION_SAMPLE_MS) != 0U) {
        ++samples;
    }
    return samples == 0U ? 1U : samples;
}

static uint32_t vibration_confirm_ms(void)
{
    uint32_t confirm_s = g_work_mode.config.vibration_confirm_s;
    if (confirm_s > WORK_MODE_MAX_VIBRATION_CONFIRM_S)
        confirm_s = WORK_MODE_MAX_VIBRATION_CONFIRM_S;
    return confirm_s * WORK_MODE_MS_PER_SECOND;
}

static bool is_mode_entry_action(work_mode_action_type_t type)
{
    return type == WORK_ACTION_SET_LOGICAL_ACC ||
           type == WORK_ACTION_GPS_ON ||
           type == WORK_ACTION_REPORT_ENTRY ||
           type == WORK_ACTION_GPS_OFF ||
           type == WORK_ACTION_ENTER_STOP1;
}

static bool queued_action_is_stale(const work_mode_queued_action_t *queued)
{
    return queued->mode_entry &&
           queued->generation != g_work_mode.mode_generation;
}

static void fill_queued_action(work_mode_queued_action_t *queued,
                               work_mode_action_type_t type, bool acc_on,
                               uint32_t alarm_bits,
                               bool historical_position)
{
    queued->action.type = type;
    queued->action.acc_on = acc_on;
    queued->action.alarm_bits = alarm_bits;
    queued->action.historical_position = historical_position;
    queued->generation = g_work_mode.mode_generation;
    queued->mode_entry = is_mode_entry_action(type);
}

static bool enqueue_direct_queued(const work_mode_queued_action_t *queued)
{
    uint8_t index;

    if (g_work_mode.action_count >= WORK_MODE_ACTION_QUEUE_CAPACITY) {
        return false;
    }

    index = (uint8_t)((g_work_mode.action_head + g_work_mode.action_count) % WORK_MODE_ACTION_QUEUE_CAPACITY);
    g_work_mode.actions[index] = *queued;
    ++g_work_mode.action_count;
    return true;
}

static bool enqueue_direct(work_mode_action_type_t type, bool acc_on,
                           uint32_t alarm_bits, bool historical_position)
{
    work_mode_queued_action_t queued;

    fill_queued_action(&queued, type, acc_on, alarm_bits, historical_position);
    return enqueue_direct_queued(&queued);
}

static void remove_pending_at(uint8_t index)
{
    uint8_t i;

    for (i = index; (uint8_t)(i + 1U) < g_work_mode.pending_count; ++i) {
        g_work_mode.pending_actions[i] = g_work_mode.pending_actions[i + 1U];
    }
    --g_work_mode.pending_count;
}

static void discard_stale_pending_actions(void)
{
    uint8_t pass;
    uint8_t index = 0U;

    for (pass = 0U; pass < WORK_MODE_PENDING_ACTION_CAPACITY; ++pass) {
        if (index >= g_work_mode.pending_count) {
            return;
        }
        if (queued_action_is_stale(&g_work_mode.pending_actions[index])) {
            remove_pending_at(index);
        } else {
            ++index;
        }
    }
}

static bool remember_pending_essential(work_mode_action_type_t type, bool acc_on,
                                       uint32_t alarm_bits,
                                       bool historical_position)
{
    work_mode_queued_action_t queued;

    if (!is_mode_entry_action(type)) {
        return false;
    }
    discard_stale_pending_actions();
    if (g_work_mode.pending_count >= WORK_MODE_PENDING_ACTION_CAPACITY) {
        return false;
    }
    fill_queued_action(&queued, type, acc_on, alarm_bits, historical_position);
    g_work_mode.pending_actions[g_work_mode.pending_count] = queued;
    ++g_work_mode.pending_count;
    return true;
}

static void flush_pending_essentials(void)
{
    uint8_t pass;

    for (pass = 0U; pass < WORK_MODE_PENDING_ACTION_CAPACITY; ++pass) {
        if (g_work_mode.pending_count == 0U) {
            return;
        }
        if (queued_action_is_stale(&g_work_mode.pending_actions[0])) {
            remove_pending_at(0U);
            continue;
        }
        if (!enqueue_direct_queued(&g_work_mode.pending_actions[0])) {
            return;
        }
        remove_pending_at(0U);
    }
}

static bool enqueue_action(work_mode_action_type_t type, bool acc_on,
                           uint32_t alarm_bits, bool historical_position)
{
    uint8_t index;

    if (type == WORK_ACTION_REPORT_ALARM) {
        uint8_t offset;
        for (offset = 0U; offset < g_work_mode.action_count; ++offset) {
            index = (uint8_t)((g_work_mode.action_head + offset) % WORK_MODE_ACTION_QUEUE_CAPACITY);
            if (g_work_mode.actions[index].action.type == WORK_ACTION_REPORT_ALARM) {
                g_work_mode.actions[index].action.alarm_bits |= alarm_bits;
                return true;
            }
        }
    }

    if (enqueue_direct(type, acc_on, alarm_bits, historical_position)) {
        return true;
    }

    return remember_pending_essential(type, acc_on, alarm_bits,
                                      historical_position);
}

static void set_deadlines(uint32_t now_s)
{
    g_work_mode.moving_deadline_s = now_s + interval_or_safe(g_work_mode.config.report_moving_s);
    g_work_mode.stopped_deadline_s = now_s + interval_or_safe(g_work_mode.config.report_stopped_s);
    g_work_mode.heartbeat_deadline_s = now_s + interval_or_safe(g_work_mode.config.heartbeat_s);
}

static void enter_realtime(uint32_t now_s)
{
    if (g_work_mode.state == WORK_MODE_REALTIME) {
        return;
    }

    ++g_work_mode.mode_generation;
    g_work_mode.state = WORK_MODE_REALTIME;
    g_work_mode.logical_acc = true;
    g_work_mode.vibration_hits = 0U;
    g_work_mode.vibration_miss_count = 0U;
    g_work_mode.vibration_started_ms = 0U;
    g_work_mode.vibration_last_hit_ms = 0U;
    s_acc_sample = 0U;
    g_work_mode.stationary_since_s = now_s;
    g_work_mode.moving_deadline_s = now_s + interval_or_safe(g_work_mode.config.report_moving_s);
    (void)enqueue_action(WORK_ACTION_SET_LOGICAL_ACC, true, 0U, false);
    (void)enqueue_action(WORK_ACTION_GPS_ON, true, 0U, false);
    (void)enqueue_action(WORK_ACTION_REPORT_ENTRY, true, 0U, false);
}

static void enter_stationary(uint32_t now_s, bool gps_valid)
{
    (void)gps_valid;
    if (g_work_mode.state == WORK_MODE_STATIONARY_SLEEP) {
        return;
    }

    ++g_work_mode.mode_generation;
    g_work_mode.state = WORK_MODE_STATIONARY_SLEEP;
    g_work_mode.logical_acc = false;
    g_work_mode.vibration_hits = 0U;
    g_work_mode.vibration_miss_count = 0U;
    g_work_mode.vibration_started_ms = 0U;
    g_work_mode.vibration_last_hit_ms = 0U;
    g_work_mode.stopped_deadline_s = now_s + interval_or_safe(g_work_mode.config.report_stopped_s);
    g_work_mode.heartbeat_deadline_s = now_s + interval_or_safe(g_work_mode.config.heartbeat_s);
    (void)enqueue_action(WORK_ACTION_SET_LOGICAL_ACC, false, 0U, false);
    /* Capture the trusted fix before powering GNSS down, then report the
     * retained position as the STOP1 entry packet. */
    (void)enqueue_action(WORK_ACTION_GPS_OFF, false, 0U, false);
    (void)enqueue_action(WORK_ACTION_REPORT_ENTRY, false, 0U, true);
    (void)enqueue_action(WORK_ACTION_ENTER_STOP1, false, 0U, false);
}

static void process_vibration(uint32_t now_s, uint32_t now_ms, bool vibration_hit)
{
    if (now_ms == 0U)
        now_ms = now_s * WORK_MODE_MS_PER_SECOND;
    if (!vibration_hit) {
        if (g_work_mode.vibration_hits != 0U &&
            (uint32_t)(now_ms - g_work_mode.vibration_last_hit_ms) >
            WORK_MODE_VIBRATION_MAX_GAP_MS) {
            g_work_mode.vibration_hits = 0U;
            g_work_mode.vibration_miss_count = 0U;
            g_work_mode.vibration_started_ms = 0U;
        }
        return;
    }

    g_work_mode.vibration_miss_count = 0U;
    if (g_work_mode.vibration_hits == 0U ||
        (uint32_t)(now_ms - g_work_mode.vibration_last_hit_ms) >
        WORK_MODE_VIBRATION_MAX_GAP_MS) {
        g_work_mode.vibration_started_ms = now_ms;
        g_work_mode.vibration_hits = 0U;
    }
    g_work_mode.vibration_last_hit_ms = now_ms;

    if (g_work_mode.vibration_hits < vibration_samples_required()) {
        ++g_work_mode.vibration_hits;
    }
    if (g_work_mode.vibration_hits != 0U &&
        (uint32_t)(now_ms - g_work_mode.vibration_started_ms) >=
        vibration_confirm_ms()) {
        enter_realtime(now_s);
    }
}

void work_mode_init(const work_mode_config_t *cfg, uint32_t now_s, bool acc_high)
{
    g_work_mode.config.report_moving_s = 30U;
    g_work_mode.config.report_stopped_s = 180U;
    g_work_mode.config.heartbeat_s = 180U;
    g_work_mode.config.stationary_timeout_s = 300U;
    g_work_mode.config.vibration_confirm_s = 6U;
    if (cfg != 0) {
        g_work_mode.config = *cfg;
    }
    g_work_mode.state = WORK_MODE_BOOT_MONITOR;
    /* Startup monitoring reports the vehicle as active until the stationary
     * timeout expires.  This keeps the first five minutes on the same 30 s
     * 0x0200 cadence as realtime mode even when the physical ACC input is low.
     */
    g_work_mode.logical_acc = true;
    g_work_mode.previous_acc_high = acc_high;
    /* Zero is the millisecond debounce-candidate sentinel.  The previous
     * implementation stored the boot second here, causing the first PA12
     * sample after boot to be compared against a mixed time base and accepted
     * immediately. */
    g_work_mode.boot_monitor_started_s = 0U;
    g_work_mode.stationary_since_s = now_s;
    g_work_mode.action_head = 0U;
    g_work_mode.action_count = 0U;
    g_work_mode.pending_count = 0U;
    g_work_mode.mode_generation = 0U;
    g_work_mode.vibration_hits = 0U;
    g_work_mode.vibration_miss_count = 0U;
    g_work_mode.vibration_started_ms = 0U;
    g_work_mode.vibration_last_hit_ms = 0U;
    s_pending_alarm_bits = 0U;
    /* Do not carry a debounced PA12 sample across a reinitialization.  Host
     * policy tests and the firmware both reinitialize the mode manager after
     * wake/reconnect paths, and a stale timestamp can otherwise commit an
     * edge against the new time base. */
    s_acc_sample = 0U;
    set_deadlines(now_s);
    if (acc_high) {
        enter_realtime(now_s);
    } else {
        (void)enqueue_action(WORK_ACTION_SET_LOGICAL_ACC, true, 0U, false);
        /* Boot monitor remains logically active and emits an immediate ON
         * entry location even when the physical ACC input is low. */
        (void)enqueue_action(WORK_ACTION_REPORT_ENTRY, true, 0U, false);
    }
}

void work_mode_configure(const work_mode_config_t *cfg, uint32_t now_s)
{
    if (cfg == 0) {
        return;
    }

    g_work_mode.config = *cfg;
    set_deadlines(now_s);
}

void work_mode_step(const work_mode_input_t *input)
{
    bool confirmed_acc_high;
    bool raw_acc_high;
    bool acc_falling;
    bool acc_committed = false;
    bool old_acc_high;
    uint32_t now_ms;

    if (input == 0) {
        return;
    }

    raw_acc_high = (s_acc_sample & ACC_SAMPLE_VALID_MASK) != 0U ?
                   (s_acc_sample & ACC_SAMPLE_HIGH_MASK) != 0U : input->acc_high;
    old_acc_high = g_work_mode.previous_acc_high;
    if ((s_acc_sample & ACC_SAMPLE_VALID_MASK) == 0U) {
        /* Compatibility path for callers that cannot supply a millisecond
         * sample timestamp. Firmware always supplies one via PA12. */
        g_work_mode.previous_acc_high = raw_acc_high;
        g_work_mode.boot_monitor_started_s = 0U;
        confirmed_acc_high = raw_acc_high;
        acc_falling = old_acc_high && !confirmed_acc_high;
    } else {
        now_ms = s_acc_sample & ACC_SAMPLE_TIME_MASK;
        s_acc_sample = 0U;
        if (g_work_mode.boot_monitor_started_s == 0U) {
            if (raw_acc_high != g_work_mode.previous_acc_high) {
                /* Candidate is necessarily the opposite of the committed level. */
                g_work_mode.boot_monitor_started_s = now_ms;
            }
        } else if (raw_acc_high == g_work_mode.previous_acc_high) {
            /* Candidate reverted before confirmation; cancel debounce. */
            g_work_mode.boot_monitor_started_s = 0U;
        } else if ((uint32_t)(now_ms - g_work_mode.boot_monitor_started_s) >=
                   WORK_MODE_ACC_DEBOUNCE_MS) {
            g_work_mode.previous_acc_high = raw_acc_high;
            g_work_mode.boot_monitor_started_s = 0U;
            acc_committed = true;
        }
        confirmed_acc_high = g_work_mode.previous_acc_high;
        acc_falling = acc_committed && old_acc_high && !confirmed_acc_high;
    }
    if (acc_falling) {
        enter_stationary(input->now_s, input->gps_valid);
    }

    /* Alarms wake STOP1 into realtime before the alarm report is queued. */
    if (input->alarm_bits != 0U &&
        g_work_mode.state == WORK_MODE_STATIONARY_SLEEP) {
        enter_realtime(input->now_s);
    }

    if (input->alarm_bits != 0U) {
        (void)enqueue_action(WORK_ACTION_REPORT_ALARM, g_work_mode.logical_acc,
                             input->alarm_bits, !input->gps_valid);
    }

    if (!acc_falling) {
        if (confirmed_acc_high) {
            enter_realtime(input->now_s);
        } else if (input->vibration_sample_valid) {
            /* A single accelerometer spike must not postpone the five-minute
             * boot-to-sleep deadline.  Only an already-confirmed realtime
             * vibration session refreshes stationary_since_s; the episode
             * itself is validated by process_vibration() over six seconds. */
            if (input->vibration_hit && g_work_mode.state == WORK_MODE_REALTIME) {
                g_work_mode.stationary_since_s = input->now_s;
            }
            if (g_work_mode.state != WORK_MODE_REALTIME) {
                process_vibration(input->now_s, input->now_ms, input->vibration_hit);
            }
        }
    }

    /* Do not power GNSS down at the boot-monitor deadline until a GPS fix
     * has actually been acquired at least once: otherwise a slow cold start
     * (poor sky view, no AGNSS) leaves the device with GNSS off and no
     * trusted fix ever captured, silencing 0200 reports until an unrelated
     * ACC/vibration event forces GPS back on. Keep retrying (30s cadence,
     * live 0200 attempts) indefinitely until the first valid fix arrives. */
    if (g_work_mode.state == WORK_MODE_BOOT_MONITOR && input->gps_valid &&
        deadline_reached(input->now_s,
                         g_work_mode.stationary_since_s +
                         interval_or_safe(g_work_mode.config.stationary_timeout_s))) {
        enter_stationary(input->now_s, input->gps_valid);
    }

    /* A vibration wake may enter REALTIME while the physical ACC remains
     * inactive. Once the vibration has stopped for the configured stationary
     * interval, return to sleep just as we do during boot monitoring. */
    if (g_work_mode.state == WORK_MODE_REALTIME &&
        !confirmed_acc_high && input->vibration_sample_valid &&
        !input->vibration_hit &&
        deadline_reached(input->now_s,
                         g_work_mode.stationary_since_s +
                         interval_or_safe(g_work_mode.config.stationary_timeout_s))) {
        enter_stationary(input->now_s, input->gps_valid);
    }

    if (g_work_mode.state == WORK_MODE_REALTIME &&
        deadline_reached(input->now_s, g_work_mode.moving_deadline_s)) {
        if (enqueue_action(WORK_ACTION_REPORT_LOCATION, true, 0U, !input->gps_valid)) {
            g_work_mode.moving_deadline_s = input->now_s +
                                             interval_or_safe(g_work_mode.config.report_moving_s);
        }
    }

    /* During the five-minute boot monitor, keep sending the configured
     * moving-period 0x0200 reports with ACC logically ON.  The transition to
     * stationary sleep is evaluated above, so the timeout tick emits only the
     * ACC-OFF entry report and never an extra boot report.
     */
    if (g_work_mode.state == WORK_MODE_BOOT_MONITOR &&
        deadline_reached(input->now_s, g_work_mode.moving_deadline_s) &&
        enqueue_action(WORK_ACTION_REPORT_LOCATION, true, 0U,
                       !input->gps_valid)) {
        g_work_mode.moving_deadline_s = input->now_s +
                                         interval_or_safe(g_work_mode.config.report_moving_s);
    }

    if (g_work_mode.state == WORK_MODE_STATIONARY_SLEEP) {
        /* GNSS is powered off in this state; only the retained last-trusted
         * snapshot (kept current by gps_advance_last_trusted_seconds() on
         * every STOP1 wake) has a valid clock. input->gps_valid can stay
         * stuck true here because TICK_MS() freezes during STOP1, so it
         * must not gate this choice. */
        if (deadline_reached(input->now_s, g_work_mode.stopped_deadline_s) &&
            enqueue_action(WORK_ACTION_REPORT_LOCATION, false, 0U, true)) {
            g_work_mode.stopped_deadline_s = input->now_s +
                                              interval_or_safe(g_work_mode.config.report_stopped_s);
        }
        /* Heartbeats are scheduled by jt808_process(), the single transport
         * owner.  Keeping one scheduler prevents duplicate 0x0002 frames. */
    }

    flush_pending_essentials();
}

bool work_mode_next_action(work_mode_action_t *out)
{
    uint8_t pass;

    if (out == 0 || g_work_mode.action_count == 0U) {
        flush_pending_essentials();
        if (out == 0 || g_work_mode.action_count == 0U) {
            return false;
        }
    }

    for (pass = 0U;
         pass < (WORK_MODE_ACTION_QUEUE_CAPACITY +
                 WORK_MODE_PENDING_ACTION_CAPACITY);
         ++pass) {
        work_mode_queued_action_t queued;

        if (g_work_mode.action_count == 0U) {
            flush_pending_essentials();
            if (g_work_mode.action_count == 0U) {
                break;
            }
        }
        queued = g_work_mode.actions[g_work_mode.action_head];
        g_work_mode.action_head = (uint8_t)((g_work_mode.action_head + 1U) % WORK_MODE_ACTION_QUEUE_CAPACITY);
        --g_work_mode.action_count;
        if (queued_action_is_stale(&queued)) {
            continue;
        }
        flush_pending_essentials();
        *out = queued.action;
        return true;
    }
    return false;
}

work_mode_state_t work_mode_state(void)
{
    return g_work_mode.state;
}

bool work_mode_logical_acc(void)
{
    return g_work_mode.logical_acc;
}

uint16_t work_mode_vibration_hits(void)
{
    return (uint16_t)g_work_mode.vibration_hits;
}

uint16_t work_mode_vibration_required(void)
{
    return (uint16_t)vibration_samples_required();
}

void work_mode_notify_alarm(uint32_t alarm_bits)
{
    s_pending_alarm_bits |= alarm_bits;
}

uint32_t work_mode_take_alarm(void)
{
    uint32_t bits = s_pending_alarm_bits;
    s_pending_alarm_bits = 0U;
    return bits;
}

void work_mode_retry_action(const work_mode_action_t *action)
{
    if (action != 0) {
        (void)enqueue_action(action->type, action->acc_on,
                             action->alarm_bits, action->historical_position);
    }
}

void work_mode_config_changed(const device_config_t *cfg, uint32_t now_s)
{
    work_mode_config_t next;
    if (cfg == 0) return;
    next.report_moving_s = cfg->report_moving_s;
    next.report_stopped_s = cfg->report_stopped_s;
    next.heartbeat_s = cfg->heartbeat_s;
    next.stationary_timeout_s = 300U;
    next.vibration_confirm_s = 6U;
    work_mode_configure(&next, now_s);
}
