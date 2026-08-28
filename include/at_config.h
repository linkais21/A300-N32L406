#ifndef AT_CONFIG_H
#define AT_CONFIG_H

#include <stdint.h>
#include <stdbool.h>
#include "f39_reply.h"

void at_config_init(void);
/* Feed one byte from debug/RS232 UART into the command parser */
void at_config_feed(uint8_t byte);
/* Process pending command (call from main loop) */
void at_config_process(void);
/* SMS invokes this bounded entry; serial feed remains independently permissive. */
/* Execute one queued F39 SMS and hand the bounded reply back to sender. */
bool at_config_execute_sms(const char *sender, const uint8_t *text, uint16_t len);

typedef int (*at_config_sms_send_fn)(const char *to, const char *text, void *context);
typedef void (*at_config_reset_fn)(uint32_t delay_ms, void *context);
void at_config_bind_f39(f39_platform_t *platform,
                        at_config_sms_send_fn send,
                        at_config_reset_fn schedule_reset,
                        void *context);
void at_config_receive_sms(const char *from, const uint8_t *text, uint16_t len);

#endif
