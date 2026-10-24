#include "peripherals.h"
#include "config.h"
#include "hw_init.h"
#include "debug_uart.h"
#include "n32l40x.h"
#include "sms_ingress.h"
#include "ec800m.h"
#ifdef A300_FIRMWARE_IMAGE
#include "at_config.h"
#endif
#include <string.h>

#ifdef A300_FIRMWARE_IMAGE
static bool s_sms_result_bound;
#else
static sms_recv_cb_t s_sms_cb;
static sms_send_result_cb_t s_sms_result_cb;
static void sms_dispatch(const char *from, const uint8_t *cmd, uint16_t len)
{
    char text[SMS_COMMAND_MAX_LEN];
    if (!s_sms_cb || len >= sizeof(text)) return;
    memcpy(text, cmd, len);
    text[len] = '\0';
    s_sms_cb(from, text);
}
#endif

void sms_set_recv_cb(sms_recv_cb_t cb)
{
#ifdef A300_FIRMWARE_IMAGE
    sms_ingress_set_callback(cb == sms_command_execute ? at_config_receive_sms : NULL);
#else
    s_sms_cb = cb;
    sms_ingress_set_callback(sms_dispatch);
#endif
}

int sms_send(const char *phone, const char *text)
{
    return ec800m_sms_send(phone, text);
}

void sms_set_send_result_cb(sms_send_result_cb_t cb)
{
#ifdef A300_FIRMWARE_IMAGE
    s_sms_result_bound = cb == f39_sms_result;
#else
    s_sms_result_cb = cb;
#endif
}
void sms_send_complete(bool success)
{
#ifdef A300_FIRMWARE_IMAGE
    if (s_sms_result_bound) f39_sms_result(success);
#else
    if (s_sms_result_cb) s_sms_result_cb(success);
#endif
}

void sms_process_urc(const char *line)
{
    sms_ingress_feed_line(line);
}

void sms_process(void)
{
    sms_ingress_process();
}
