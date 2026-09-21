#include "blind_zone_replay.h"
#include "blind_zone.h"
#include "config.h"
#include "jt808.h"
#include "log_platform.h"
#include "tcp_manager.h"
#include <stdbool.h>

#define REPLAY_BODY_LIMIT       500U
#define REPLAY_FIXED_BYTES      3U
#define REPLAY_ITEM_OVERHEAD    2U
#define REPLAY_RECORDS_PER_BATCH \
    ((REPLAY_BODY_LIMIT - REPLAY_FIXED_BYTES) / \
     (REPLAY_ITEM_OVERHEAD + BLIND_ZONE_LOCATION_MAX))

typedef struct {
    bool active;
    bool acknowledged;
    uint16_t serial;
    uint32_t first_sequence;
    uint32_t sent_ms;
    uint8_t count;
    uint8_t channel;
    uint32_t generation;
} replay_inflight_t;

static replay_inflight_t s_inflight;

bool blind_zone_replay_busy(void) { return s_inflight.active; }
static blind_zone_record_t s_records[REPLAY_RECORDS_PER_BATCH];
static uint8_t s_body[REPLAY_BODY_LIMIT];

void blind_zone_replay_reset(void)
{
    s_inflight.active = false;
    s_inflight.acknowledged = false;
    s_inflight.serial = 0U;
    s_inflight.first_sequence = 0U;
    s_inflight.sent_ms = 0U;
    s_inflight.count = 0U;
    s_inflight.channel = 0U;
    s_inflight.generation = 0U;
}

static void body_u16(uint16_t *position, uint16_t value)
{
    s_body[(*position)++] = (uint8_t)(value >> 8);
    s_body[(*position)++] = (uint8_t)value;
}

void blind_zone_replay_process(void)
{
    uint32_t first_sequence;
    uint16_t position;
    uint16_t serial;
    uint8_t count;
    uint8_t i;

    if (!blind_zone_ready()) return;
    /* A surviving backup connection must not keep an old main transaction
     * alive. Retain the records and start a new batch on an online session. */
    if (s_inflight.active &&
        (!jt808_channel_online(s_inflight.channel) ||
         tcp_manager_session_generation(s_inflight.channel) != s_inflight.generation))
        blind_zone_replay_reset();
    if (!jt808_is_online()) {
        s_inflight.active = false;
        s_inflight.acknowledged = false;
        return;
    }

    if (s_inflight.active && s_inflight.acknowledged) {
        blind_zone_result_t consumed =
            blind_zone_consume(s_inflight.first_sequence, s_inflight.count);
        if (consumed == BLIND_ZONE_STALE) {
            s_inflight.active = false;
            s_inflight.acknowledged = false;
            return;
        }
        if (consumed != BLIND_ZONE_OK) return;
        s_inflight.active = false;
        s_inflight.acknowledged = false;
        log_platform_on_blind_zone_uploaded();
        return;
    }

    if (s_inflight.active) {
        if ((uint32_t)(TICK_MS() - s_inflight.sent_ms) <=
            BLIND_ZONE_REPLAY_ACK_TIMEOUT_MS)
            return;
        s_inflight.active = false;
    }

    count = blind_zone_peek(s_records, (uint8_t)REPLAY_RECORDS_PER_BATCH,
                            &first_sequence);
    if (count == 0U) return;

    position = 0U;
    body_u16(&position, count);
    s_body[position++] = 1U; /* blind-zone supplemental location batch */
    for (i = 0U; i < count; ++i) {
        uint8_t j;
        if (s_records[i].length > BLIND_ZONE_LOCATION_MAX ||
            position + REPLAY_ITEM_OVERHEAD + s_records[i].length > sizeof(s_body))
            return;
        body_u16(&position, s_records[i].length);
        for (j = 0U; j < s_records[i].length; ++j)
            s_body[position++] = s_records[i].location[j];
    }

    s_inflight.channel = jt808_online_channel();
    s_inflight.generation = tcp_manager_session_generation(s_inflight.channel);
    if (jt808_send_raw_tracked(MSG_BLIND_ZONE_BATCH, s_body, position, &serial) != 0)
        return;
    s_inflight.active = true;
    s_inflight.acknowledged = false;
    s_inflight.serial = serial;
    s_inflight.first_sequence = first_sequence;
    s_inflight.count = count;
    s_inflight.sent_ms = TICK_MS();
}

void blind_zone_replay_on_general_ack(uint8_t channel, uint32_t generation,
                                      uint16_t reply_serial,
                                      uint16_t reply_msg_id,
                                      uint8_t result)
{
    if (!s_inflight.active || s_inflight.acknowledged ||
        channel != s_inflight.channel || generation != s_inflight.generation ||
        reply_serial != s_inflight.serial ||
        reply_msg_id != MSG_BLIND_ZONE_BATCH || result != 0U)
        return;
    s_inflight.acknowledged = true;
}
