#ifndef AT_CONFIG_H
#define AT_CONFIG_H

#include <stdint.h>
#include <stdbool.h>
#include "f39_reply.h"

void at_config_init(void);
/* Single debug UART ISR producer; not reentrant across multiple UARTs.
 * CR/LF commits one line (up to 127 bytes; excess bytes are truncated).
 * A committed slot is immutable until main copies it. Input arriving while
 * busy is dropped through CR/LF, including any tail arriving after release.
 * Senders must wait for the command response before sending the next line. */
void at_config_feed(uint8_t byte);
/* Single main-loop consumer, non-reentrant; parses a private snapshot. */
void at_config_process(void);
/* SMS invokes this bounded entry; serial feed remains independently permissive. */
/* Execute one queued F39 SMS and hand the bounded reply back to sender. */
bool at_config_execute_sms(const char *sender, const uint8_t *text, uint16_t len);
/* Execute a command delivered over JT808 0x8300 text delivery. The frame is
 * acknowledged by a terminal general response, so no reply text is produced. */
bool at_config_execute_text_command(const uint8_t *text, uint16_t len);
/* The callback runs after validation/persistence but before reconnect,
 * re-registration, PDP restart or scheduled reset. Called once on failure too. */
typedef void (*at_config_text_ack_fn)(bool success, void *context);
bool at_config_execute_text_command_ack(const uint8_t *text, uint16_t len,
                                       at_config_text_ack_fn ack, void *context);

typedef int (*at_config_sms_send_fn)(const char *to, const char *text, void *context);
typedef void (*at_config_reset_fn)(uint32_t delay_ms, void *context);
void at_config_bind_f39(f39_platform_t *platform,
                        at_config_sms_send_fn send,
                        at_config_reset_fn schedule_reset,
                        void *context);
void at_config_receive_sms(const char *from, const uint8_t *text, uint16_t len);

#endif
