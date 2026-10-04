#ifndef PERIPHERALS_H
#define PERIPHERALS_H
#include <stdint.h>
#include <stdbool.h>
#include "sms_command.h"

/* ── SMS ──────────────────────────────────────────────────────────────────── */
int  sms_send(const char *phone, const char *text);
typedef void (*sms_send_result_cb_t)(bool success);
void sms_set_send_result_cb(sms_send_result_cb_t cb);
void sms_send_complete(bool success);
/* Callback: set this to handle incoming SMS */
typedef void (*sms_recv_cb_t)(const char *from, const char *text);
void sms_set_recv_cb(sms_recv_cb_t cb);
void sms_process_urc(const char *urc_line); /* feed URC lines from EC800M */
void sms_process(void);                      /* consume one approved command */
#ifdef A300_FIRMWARE_IMAGE
void sms_command_execute(const char *from, const char *text);
#endif

#endif
