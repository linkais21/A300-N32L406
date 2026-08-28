#include "peripherals.h"
#include "config.h"
#include "hw_init.h"
#include "debug_uart.h"
#include "n32l40x.h"
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
static char s_sms_from[20];
static bool s_sms_pending;

void sms_set_recv_cb(sms_recv_cb_t cb) { s_sms_cb = cb; }

int sms_send(const char *phone, const char *text)
{
    (void)phone;
    (void)text;
    return 0;
}

void sms_process_urc(const char *line)
{
    const char *q1;
    const char *q2;
    if (!line) return;
    if (strncmp(line, "+CMT:", 5) == 0) {
        q1 = strchr(line, '"');
        q2 = q1 ? strchr(q1 + 1, '"') : 0;
        if (q2 && (uint16_t)(q2 - q1 - 1) < sizeof(s_sms_from)) {
            memcpy(s_sms_from, q1 + 1, (uint16_t)(q2 - q1 - 1));
            s_sms_from[q2 - q1 - 1] = '\0';
            s_sms_pending = true;
        }
        return;
    }
    if (s_sms_pending && line[0] != '+') {
        uint16_t len = 0;
        while (len < SMS_COMMAND_MAX_LEN && line[len] != '\0') ++len;
        if (len < SMS_COMMAND_MAX_LEN && sms_queue_push((const uint8_t *)line, len) && s_sms_cb)
            s_sms_cb(s_sms_from, line);
        s_sms_pending = false;
    }
}
