#include "jt808_session.h"

#include <stddef.h>
#include <string.h>

#define JT808_RETRY_MS   5000U
#define JT808_BACKOFF_MS 60000U
#define JT808_MAX_ATTEMPTS 3U

static bool deadline_reached(uint32_t now, uint32_t deadline)
{
    return (int32_t)(now - deadline) >= 0;
}

static void reset_transaction(jt808_session_t *session)
{
    session->state = JT808_SESSION_IDLE;
    session->pending_serial = 0U;
    session->sent_ms = 0U;
    session->backoff_until_ms = 0U;
    session->attempts = 0U;
    session->pending_valid = false;
    session->waiting_first_fix = false;
}

void jt808_session_init(jt808_session_t *session, uint8_t channel)
{
    if (session == NULL) return;
    memset(session, 0, sizeof(*session));
    session->channel = channel;
    session->state = JT808_SESSION_IDLE;
}

void jt808_session_sync_link(jt808_session_t *session, bool open,
                             uint32_t generation)
{
    if (session == NULL) return;
    if (!open || !session->link_open || session->generation != generation) {
        reset_transaction(session);
        session->generation = generation;
    }
    session->link_open = open;
}

jt808_session_action_t jt808_session_next_action(
    const jt808_session_t *session, bool has_auth, uint32_t now)
{
    if (session == NULL || !session->link_open ||
        session->state == JT808_SESSION_ONLINE)
        return JT808_ACTION_NONE;
    if (session->state == JT808_SESSION_BACKOFF) {
        if (!deadline_reached(now, session->backoff_until_ms))
            return JT808_ACTION_NONE;
        return has_auth ? JT808_ACTION_AUTH : JT808_ACTION_REGISTER;
    }
    if (session->state == JT808_SESSION_IDLE)
        return has_auth ? JT808_ACTION_AUTH : JT808_ACTION_REGISTER;
    if (!deadline_reached(now, session->sent_ms + JT808_RETRY_MS) ||
        session->attempts >= JT808_MAX_ATTEMPTS)
        return JT808_ACTION_NONE;
    return session->state == JT808_SESSION_REGISTERING ?
           JT808_ACTION_REGISTER : JT808_ACTION_AUTH;
}

void jt808_session_mark_sent(jt808_session_t *session,
                             jt808_session_action_t action,
                             uint16_t serial, uint32_t now)
{
    jt808_session_state_t target_state;

    if (session == NULL || !session->link_open || action == JT808_ACTION_NONE)
        return;
    target_state = action == JT808_ACTION_REGISTER ?
                   JT808_SESSION_REGISTERING : JT808_SESSION_AUTHENTICATING;
    if (session->state == JT808_SESSION_IDLE ||
        session->state == JT808_SESSION_BACKOFF ||
        session->state != target_state)
        session->attempts = 0U;
    session->state = target_state;
    session->pending_serial = serial;
    session->sent_ms = now;
    session->backoff_until_ms = 0U;
    session->pending_valid = true;
    ++session->attempts;
}

void jt808_session_mark_send_failed(jt808_session_t *session,
                                    jt808_session_action_t action,
                                    uint32_t now)
{
    jt808_session_state_t target_state;

    if (session == NULL || !session->link_open || action == JT808_ACTION_NONE)
        return;
    target_state = action == JT808_ACTION_REGISTER ?
                   JT808_SESSION_REGISTERING : JT808_SESSION_AUTHENTICATING;
    if (session->state == JT808_SESSION_BACKOFF &&
        !deadline_reached(now, session->backoff_until_ms))
        return;
    if (session->state != target_state)
        session->attempts = 0U;
    if (session->attempts < JT808_MAX_ATTEMPTS)
        ++session->attempts;
    session->state = target_state;
    session->pending_valid = false;
    session->sent_ms = now;
    session->backoff_until_ms = 0U;
    if (session->attempts >= JT808_MAX_ATTEMPTS) {
        session->state = JT808_SESSION_BACKOFF;
        session->backoff_until_ms = now + JT808_BACKOFF_MS;
    }
}

bool jt808_session_accept_register(const jt808_session_t *session,
                                   uint32_t generation,
                                   uint16_t response_serial)
{
    return session != NULL && session->link_open &&
           session->state == JT808_SESSION_REGISTERING &&
           session->pending_valid && session->generation == generation &&
           session->pending_serial == response_serial;
}

void jt808_session_consume_register(jt808_session_t *session)
{
    if (session != NULL) session->pending_valid = false;
}

bool jt808_session_accept_auth(const jt808_session_t *session,
                               uint32_t generation,
                               uint16_t response_serial)
{
    return session != NULL && session->link_open &&
           session->state == JT808_SESSION_AUTHENTICATING &&
           session->pending_valid && session->generation == generation &&
           session->pending_serial == response_serial;
}

void jt808_session_mark_online(jt808_session_t *session)
{
    if (session == NULL) return;
    session->state = JT808_SESSION_ONLINE;
    session->pending_valid = false;
    session->attempts = 0U;
    session->waiting_first_fix = true;
}

bool jt808_session_reject_or_timeout(jt808_session_t *session, uint32_t now)
{
    if (session == NULL) return false;
    session->pending_valid = false;
    if (session->attempts >= JT808_MAX_ATTEMPTS) {
        session->state = JT808_SESSION_BACKOFF;
        session->backoff_until_ms = now + JT808_BACKOFF_MS;
        return true;
    }
    return false;
}
