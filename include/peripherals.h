#ifndef PERIPHERALS_H
#define PERIPHERALS_H
#include <stdint.h>
#include <stdbool.h>
#include "sms_command.h"

/* ── RS485 ────────────────────────────────────────────────────────────────── */
void     rs485_init(uint32_t baud);
void     rs485_send(const uint8_t *data, uint16_t len);
uint16_t rs485_recv(uint8_t *buf, uint16_t max_len);  /* returns bytes read */

/* ── SMS ──────────────────────────────────────────────────────────────────── */
int  sms_send(const char *phone, const char *text);
/* Callback: set this to handle incoming SMS */
typedef void (*sms_recv_cb_t)(const char *from, const char *text);
void sms_set_recv_cb(sms_recv_cb_t cb);
void sms_process_urc(const char *urc_line); /* feed URC lines from EC800M */
void sms_process(void);                      /* consume one approved command */

#endif
