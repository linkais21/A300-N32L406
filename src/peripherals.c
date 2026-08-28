#include "peripherals.h"
#include "config.h"
#include "hw_init.h"
#include "debug_uart.h"
#include "n32l40x.h"
#include "sms_ingress.h"
#include "ec800m.h"
#include <string.h>

static uint8_t s_rs485_rx_buf[256];
static uint16_t s_rs485_rx_len;

void rs485_init(uint32_t baud)
{
    (void)baud;
    GPIO_ResetBits(RS485_CE_PORT, RS485_CE_PIN);
    s_rs485_rx_len = 0;
}

void rs485_send(const uint8_t *data, uint16_t len)
{
    (void)data;
    (void)len;
    dbg_printf("[RS485] disabled\r\n");
}

uint16_t rs485_recv(uint8_t *buf, uint16_t max_len)
{
    uint16_t n = s_rs485_rx_len < max_len ? s_rs485_rx_len : max_len;
    memcpy(buf, s_rs485_rx_buf, n);
    s_rs485_rx_len = 0;
    return n;
}

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

void sms_set_recv_cb(sms_recv_cb_t cb) { s_sms_cb = cb; sms_ingress_set_callback(sms_dispatch); }

int sms_send(const char *phone, const char *text)
{
    return ec800m_sms_send(phone, text);
}

void sms_set_send_result_cb(sms_send_result_cb_t cb) { s_sms_result_cb = cb; }
void sms_send_complete(bool success) { if (s_sms_result_cb) s_sms_result_cb(success); }

void sms_process_urc(const char *line)
{
    sms_ingress_feed_line(line);
}

void sms_process(void)
{
    sms_ingress_process();
}
