#ifndef JT808_SESSION_H
#define JT808_SESSION_H

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    JT808_SESSION_IDLE = 0,
    JT808_SESSION_REGISTERING,
    JT808_SESSION_AUTHENTICATING,
    JT808_SESSION_ONLINE,
    JT808_SESSION_BACKOFF,
} jt808_session_state_t;

typedef enum {
    JT808_ACTION_NONE = 0,
    JT808_ACTION_REGISTER,
    JT808_ACTION_AUTH,
} jt808_session_action_t;

typedef struct {
    uint8_t channel;
    jt808_session_state_t state;
    uint32_t generation;
    uint16_t pending_serial;
    uint32_t sent_ms;
    uint32_t backoff_until_ms;
    uint8_t attempts;
    bool pending_valid;
    bool waiting_first_fix;
    bool link_open;
} jt808_session_t;

void jt808_session_init(jt808_session_t *session, uint8_t channel);
void jt808_session_sync_link(jt808_session_t *session, bool open,
                             uint32_t generation);
jt808_session_action_t jt808_session_next_action(
    const jt808_session_t *session, bool has_auth, uint32_t now);
void jt808_session_mark_sent(jt808_session_t *session,
                             jt808_session_action_t action,
                             uint16_t serial, uint32_t now);
void jt808_session_mark_send_failed(jt808_session_t *session,
                                    jt808_session_action_t action,
                                    uint32_t now);
bool jt808_session_accept_register(const jt808_session_t *session,
                                   uint32_t generation,
                                   uint16_t response_serial);
void jt808_session_consume_register(jt808_session_t *session);
bool jt808_session_accept_auth(const jt808_session_t *session,
                               uint32_t generation,
                               uint16_t response_serial);
void jt808_session_mark_online(jt808_session_t *session);
bool jt808_session_reject_or_timeout(jt808_session_t *session, uint32_t now);

#endif
