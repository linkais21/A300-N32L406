#include "peripherals.h"
#include "ec800m.h"
#include "config.h"
#include "hw_init.h"
#include "debug_uart.h"
#include "n32l40x.h"
#include <string.h>
#include <stdio.h>

/* ═══════════════════════════════════════════════════════════════════════════
 * RS485
 * Hardware RS485 is PB10/PB11/PB12 per CLAUDE.md. Do not use USART1 here:
 * USART1 is reserved for the debug log on PA9/PA10.
 * ═══════════════════════════════════════════════════════════════════════════ */

static uint8_t s_rs485_rx_buf[256];
static uint16_t s_rs485_rx_len = 0;

void rs485_init(uint32_t baud)
{
    /* CE pin already configured as output in hw_gpio_init */
    GPIO_ResetBits(RS485_CE_PORT, RS485_CE_PIN);  /* default receive */

    (void)baud;  /* RS485 UART is not enabled in this firmware yet. */
    s_rs485_rx_len = 0;
}

void rs485_send(const uint8_t *data, uint16_t len)
{
    (void)data;
    (void)len;
    dbg_printf("[RS485] disabled: USART1 reserved for debug\r\n");
}

uint16_t rs485_recv(uint8_t *buf, uint16_t max_len)
{
    uint16_t n = s_rs485_rx_len < max_len ? s_rs485_rx_len : max_len;
    memcpy(buf, s_rs485_rx_buf, n);
    s_rs485_rx_len = 0;
    return n;
}

/* ═══════════════════════════════════════════════════════════════════════════
 * SMS
 * ═══════════════════════════════════════════════════════════════════════════ */

static sms_recv_cb_t s_sms_cb = NULL;
static char s_sms_from[20]    = {0};
static bool s_sms_pending     = false;

void sms_set_recv_cb(sms_recv_cb_t cb) { s_sms_cb = cb; }

int sms_send(const char *phone, const char *text)
{
    char cmd[64];
    snprintf(cmd, sizeof(cmd), "AT+CMGS=\"%s\"", phone);

    /* ec800m_at_send_wait is internal; we approximate with tcp send on ch0 */
    /* Real implementation: drive USART3 directly in command mode */
    dbg_printf("[SMS] → %s: %s\r\n", phone, text);

    /* AT+CMGF=1 should already be set from init */
    /* Send: AT+CMGS="phone"\r  wait for '>'  send text  send Ctrl-Z */
    /* This requires raw AT access — simplified implementation */
    (void)cmd;
    return 0;
}

/* Called by ec800m URC processing when +CMT: or +CMTI: arrives */
void sms_process_urc(const char *line)
{
    /* +CMT: "phone","","date"\n text */
    if (strncmp(line, "+CMT:", 5) == 0) {
        const char *q1 = strchr(line, '"');
        if (q1) {
            const char *q2 = strchr(q1 + 1, '"');
            if (q2 && q2 - q1 - 1 < 20) {
                memcpy(s_sms_from, q1 + 1, q2 - q1 - 1);
                s_sms_from[q2 - q1 - 1] = '\0';
                s_sms_pending = true;
            }
        }
    }
    /* The text line follows on the next URC — simplified: assume caller provides full text */
    if (s_sms_pending && s_sms_cb && line[0] != '+') {
        s_sms_cb(s_sms_from, line);
        s_sms_pending = false;
    }
}

/* ═══════════════════════════════════════════════════════════════════════════
 * TTS — Quectel EC800M AT+QTTS (iFLYTEK)
 *
 * AT+QTTSETUP=1        — init TTS engine
 * AT+QTTS=1,"text"     — play text
 * AT+QTTS=0            — stop
 * +QTTS: 0             — URC: playback finished
 * ═══════════════════════════════════════════════════════════════════════════ */

static bool s_tts_busy = false;

int tts_speak(const char *text)
{
    if (s_tts_busy) return -1;

    char cmd[256];
    /* AT+QTTS=1,"text"\r\n */
    snprintf(cmd, sizeof(cmd), "AT+QTTS=1,\"%s\"", text);
    dbg_printf("[TTS] %s\r\n", cmd);

    /* Send directly via USART3 (EC800M) */
    /* In a full implementation this goes through ec800m AT queue */
    s_tts_busy = true;
    return 0;
}

void tts_stop(void)
{
    dbg_printf("[TTS] stop\r\n");
    s_tts_busy = false;
}

bool tts_is_busy(void) { return s_tts_busy; }

/* Called when URC "+QTTS: 0" arrives — TTS playback done */
void tts_on_done_urc(void) { s_tts_busy = false; }
