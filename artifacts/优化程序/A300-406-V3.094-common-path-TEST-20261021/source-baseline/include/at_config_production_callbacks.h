#ifndef AT_CONFIG_PRODUCTION_CALLBACKS_H
#define AT_CONFIG_PRODUCTION_CALLBACKS_H

#include <stdbool.h>
#include <stdint.h>

void cfg_query_ack(bool success, void *context);
void jt808_text_command_ack(bool success, void *context);
void jt808_text_command_reply(const uint8_t *text, uint16_t len, void *context);

#endif
