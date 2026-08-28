#ifndef SMS_COMMAND_H
#define SMS_COMMAND_H
#include <stdbool.h>
#include <stdint.h>
#define SMS_COMMAND_MAX_LEN 192u
#define SMS_QUEUE_DEPTH 2u
bool sms_command_allowed(const char *cmd);
bool sms_queue_push(const uint8_t *data, uint16_t len);
bool sms_queue_pop(uint8_t *out, uint16_t out_size, uint16_t *out_len);
void sms_queue_reset(void);
#endif
