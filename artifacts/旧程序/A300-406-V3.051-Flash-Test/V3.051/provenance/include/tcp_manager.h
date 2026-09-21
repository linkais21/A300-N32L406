#ifndef TCP_MANAGER_H
#define TCP_MANAGER_H

#include <stdint.h>
#include <stdbool.h>
#include "ec800m.h"

/*
 * Manages JT808 TCP connections with:
 * - Automatic reconnect with exponential backoff
 * - Primary→backup server failover after N failures
 * - PDP context re-activation on pdpdeact
 */

void tcp_manager_init(void);
void tcp_manager_process(void);   /* call from main loop */

/* Force reconnect (e.g. after server config change) */
void tcp_manager_reconnect(void);

/* Returns true when primary or backup channel is OPEN */
bool tcp_manager_is_online(void);

/* The channel currently used for JT808 (main or backup) */
uint8_t tcp_manager_active_ch(void);

/* Returns true when the specified channel is connected and open */
bool tcp_manager_ch_online(uint8_t ch);
uint32_t tcp_manager_session_generation(uint8_t ch);
bool tcp_manager_ota_active(void);

#endif
