#ifndef SMS_INGRESS_H
#define SMS_INGRESS_H
#include <stdint.h>
typedef void (*sms_ingress_cb_t)(const char *from, const uint8_t *cmd, uint16_t len);
void sms_ingress_set_callback(sms_ingress_cb_t cb);
void sms_ingress_feed_line(const char *line);
void sms_ingress_process(void);
#endif
