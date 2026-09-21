#ifndef BLIND_ZONE_REPLAY_H
#define BLIND_ZONE_REPLAY_H

#include <stdint.h>
#include <stdbool.h>

#define BLIND_ZONE_REPLAY_ACK_TIMEOUT_MS 10000UL

void blind_zone_replay_reset(void);
void blind_zone_replay_process(void);
bool blind_zone_replay_busy(void);
void blind_zone_replay_on_general_ack(uint16_t reply_serial,
                                      uint16_t reply_msg_id,
                                      uint8_t result);

#endif
