#include "ec800m.h"
#include "config.h"
#include "hw_init.h"
#include "debug_uart.h"
#include "ec800m_at_response.h"
#include "peripherals.h"
#include "n32l40x.h"
#include <string.h>
#include <stdio.h>
#include <stdlib.h>

/* ── RX ring buffer (filled by DMA2_CH5) ─────────────────────────────────── */
uint8_t EC800M_RX_BUF[EC800M_RX_BUF_SIZE];  /* DMA circular buffer (global, used by hw_init.c) */
static uint16_t s_rx_rd = 0;   /* read pointer (software-maintained); DMA write pointer is hardware-maintained */

/* Set to 1 to echo every raw byte from the modem to the debug UART.
 * Invaluable for bring-up; set to 0 once the link is confirmed working. */
#define EC800M_RX_ECHO  0

/* Line accumulation for AT response parsing */
#define AT_LINE_MAX  256
static char    s_line_buf[AT_LINE_MAX];
static uint16_t s_line_len = 0;
#define AT_DEFERRED_URC_MAX 4U
static char s_deferred_urc[AT_DEFERRED_URC_MAX][AT_LINE_MAX];
static uint8_t s_deferred_urc_head;
static uint8_t s_deferred_urc_tail;
static uint8_t s_deferred_urc_count;
static bool s_cmt_body_pending;
static bool s_cmt_line_active;
static bool s_deferred_urc_processing;

/* AT command send/wait */
#define AT_RESP_MAX  512
static char    s_at_resp[AT_RESP_MAX];
static volatile bool s_at_done = false;

/* Module info */
static char s_imei[16]  = {0};
static char s_iccid[22] = {0};
static int  s_csq       = 0;

static bool iccid_hex_char(char c)
{
    return (c >= '0' && c <= '9') || (c >= 'A' && c <= 'F') ||
           (c >= 'a' && c <= 'f');
}

static char iccid_upper(char c)
{
    return c >= 'a' && c <= 'f' ? (char)(c - ('a' - 'A')) : c;
}

static bool parse_iccid_response(const char *response, char out[22])
{
    const char *p;
    char candidate[22];
    uint8_t length = 0U;
    if (response == NULL || out == NULL) return false;
    p = strstr(response, "+QCCID:");
    if (p == NULL) return false;
    p += 7U;
    while (*p == ' ' || *p == '\t') ++p;
    while (iccid_hex_char(*p) && length < 21U)
        candidate[length++] = iccid_upper(*p++);
    if (length != 19U && length != 20U) return false;
    if (iccid_hex_char(*p)) return false;
    if (*p != '\0' && *p != '\r' && *p != '\n') return false;
    candidate[length] = '\0';
    memcpy(out, candidate, (size_t)length + 1U);
    return true;
}

static bool iccid_text_valid(const char *iccid)
{
    uint8_t length = 0U;
    if (iccid == NULL) return false;
    while (iccid_hex_char(iccid[length]) && length < 21U)
        ++length;
    return iccid[length] == '\0' && (length == 19U || length == 20U);
}

static bool iccid_refresh_required(bool sim_identity_ready,
                                   const char *iccid)
{
    return sim_identity_ready && !iccid_text_valid(iccid);
}

/* State */
static ec800m_state_t s_state      = EC800M_STATE_OFF;
static uint32_t       s_state_enter_ms = 0;
static uint32_t       s_init_step   = 0;
static uint8_t        s_iccid_attempts;
static bool           s_sim_identity_ready;
static ec800m_failure_t s_failure = EC800M_FAILURE_NONE;
static int s_reg_status = -1;
static uint32_t s_last_diag_ms;
#define EC800M_DIAG_INTERVAL_MS 10000U
#define EC800M_ICCID_MAX_ATTEMPTS 3U

static bool iccid_retry_should_advance(bool parsed, uint8_t *attempts)
{
    if (attempts == NULL) return true;
    if (parsed) {
        *attempts = 0U;
        return true;
    }
    if (*attempts < EC800M_ICCID_MAX_ATTEMPTS) ++(*attempts);
    return *attempts >= EC800M_ICCID_MAX_ATTEMPTS;
}

/* TCP channels */
static tcp_channel_t s_tcp[EC800M_CH_MAX];
/* Cooperative UDP transaction.  This deliberately shares the temporary OTA
 * socket and AT owner; no fifth socket or receive buffer is allocated. */
typedef enum {
    UDP_TXN_IDLE,
    UDP_TXN_OPEN_CMD,
    UDP_TXN_WAIT_OPEN,
    UDP_TXN_SEND_CMD,
    UDP_TXN_WAIT_PROMPT,
    UDP_TXN_WAIT_SEND_OK,
    UDP_TXN_WAIT_RECV,
    UDP_TXN_QIRD_CMD,
    UDP_TXN_WAIT_QIRD,
    UDP_TXN_CLOSE_CMD,
    UDP_TXN_WAIT_CLOSE,
    UDP_TXN_DONE
} udp_txn_state_t;
#define UDP_TXN_OPEN UDP_TXN_OPEN_CMD
#define UDP_TXN_SEND UDP_TXN_SEND_CMD
#define UDP_TXN_CLOSE UDP_TXN_CLOSE_CMD
static udp_txn_state_t s_udp_txn_state;
static const char *s_udp_ip; static uint16_t s_udp_port, s_udp_len, s_udp_timeout;
static const uint8_t *s_udp_data; static uint8_t *s_udp_rx; static uint16_t s_udp_rx_cap;
static int s_udp_result;
static bool s_udp_cmd_ok, s_udp_cmd_error, s_udp_open_urc;
static bool s_udp_prompt, s_udp_recv_urc, s_udp_qird_done;
static uint16_t s_udp_qird_received;
static bool s_udp_qird_overflow;
static uint16_t s_udp_resp_len;
static bool udp_txn_active(void)
{
    return s_udp_txn_state != UDP_TXN_IDLE &&
           s_udp_txn_state != UDP_TXN_DONE;
}

/* Upper-layer receive callback */
static ec800m_recv_cb_t s_recv_cb = NULL;
static ec800m_recv_cb_t s_ota_recv_cb = NULL;
static ec800m_recv_cb_t s_agnss_recv_cb = NULL;
typedef enum { SMS_TX_IDLE, SMS_TX_QUEUED, SMS_TX_WAIT_PROMPT, SMS_TX_WAIT_RESULT } sms_tx_state_t;
static sms_tx_state_t s_sms_tx_state;
static char s_sms_phone[20];
/* Sized to hold a full F39 reply. Replies longer than one GSM-7 short message
 * are sent as a concatenated message via AT+QCMGS (AT+CMGS does not segment;
 * see Quectel_LTE_Standard(A) AT command manual, AT+QCMGS). */
static char s_sms_text[EC800M_SMS_TEXT_MAX];
static uint16_t s_sms_len;
static uint8_t s_sms_seg_total;
static uint8_t s_sms_seg_index;
static uint8_t s_sms_uid;
static bool s_sms_prompt;
static bool s_sms_prompt_line_start;
static uint32_t s_sms_deadline_ms;
typedef enum { AT_OWNER_NONE, AT_OWNER_BLOCKING, AT_OWNER_SMS, AT_OWNER_TCP } at_owner_t;
static at_owner_t s_at_owner;
static void sms_tx_process(void);

static bool at_owner_acquire(at_owner_t owner)
{
    if (owner == AT_OWNER_NONE || s_at_owner != AT_OWNER_NONE) return false;
    s_at_owner = owner;
    return true;
}

static void at_owner_release(at_owner_t owner)
{
    if (s_at_owner == owner) s_at_owner = AT_OWNER_NONE;
}

static bool usart_send_buf(const uint8_t *data, uint16_t len)
{
    /* 115200 baud needs about 87 us/byte on the wire.  Keep a 100 ms
     * hardware-stall margin without rejecting a valid 1200-byte payload. */
    uint32_t deadline = TICK_MS() + 100U + (((uint32_t)len + 7U) / 8U);
    uint16_t i;
    for (i = 0U; i < len; ++i) {
        while (USART_GetFlagStatus(EC800M_UART, USART_FLAG_TXDE) == RESET) {
            IWDG_ReloadKey();
            if ((int32_t)(TICK_MS() - deadline) >= 0) return false;
        }
        USART_SendData(EC800M_UART, data[i]);
    }
    while (USART_GetFlagStatus(EC800M_UART, USART_FLAG_TXC) == RESET) {
        IWDG_ReloadKey();
        if ((int32_t)(TICK_MS() - deadline) >= 0) return false;
    }
    return true;
}

static bool usart_send_str(const char *s)
{
    return usart_send_buf((const uint8_t *)s, (uint16_t)strlen(s));
}

/* ── RX init: DMA is configured in hw_init.c; only reset the read pointer here ─────────── */
static void rx_irq_init(void)
{
    s_rx_rd = 0;  /* reset read pointer; DMA write pointer is hardware-maintained */
}

/* DMA2_Channel5 RX interrupt — marks half-transfer and transfer-complete events */
/* ── DMA interrupt handler (DMA_Channel5 for UART5 RX) ───────────────────── */
void DMA_Channel5_IRQHandler(void)
{
    /* Half-transfer and transfer-complete interrupts — flag only; data processed in main loop */
    if (DMA_GetFlagStatus(DMA_FLAG_HT5, DMA) != RESET) {
        DMA_ClearFlag(DMA_FLAG_HT5, DMA);
    }
    if (DMA_GetFlagStatus(DMA_FLAG_TC5, DMA) != RESET) {
        DMA_ClearFlag(DMA_FLAG_TC5, DMA);
    }
}

/* ── Low-level send ───────────────────────────────────────────────────────── */
/* ── Send AT command and wait for response (blocking, timeout ms) ─────────── */
static uint16_t s_at_resp_len = 0;  /* actual byte count (including \0) */
static uint16_t *s_at_resp_pos_ref;
static uint16_t s_at_resp_line_start;
static void process_rx_byte(char c);
static void process_urc(const char *line);
static void process_deferred_urc_one(void);
static void udp_note_line(const char *line);

static bool parse_uint_field(const char **cursor, unsigned maximum,
                             unsigned *value)
{
    const char *p;
    unsigned result = 0U;
    uint8_t digits = 0U;
    if (cursor == NULL || *cursor == NULL || value == NULL) return false;
    p = *cursor;
    while (*p >= '0' && *p <= '9') {
        unsigned digit = (unsigned)(*p - '0');
        if (result > (maximum - digit) / 10U) return false;
        result = result * 10U + digit;
        ++digits; ++p;
    }
    if (digits == 0U || result > maximum) return false;
    *cursor = p; *value = result;
    return true;
}

static bool parse_prefixed_uint(const char *line, const char *prefix,
                                unsigned maximum, unsigned *value)
{
    const char *p;
    size_t length;
    if (line == NULL || prefix == NULL) return false;
    length = strlen(prefix);
    if (strncmp(line, prefix, length) != 0) return false;
    p = line + length;
    return parse_uint_field(&p, maximum, value) && *p == '\0';
}

static bool parse_qiopen(const char *line, unsigned *channel,
                         unsigned *error)
{
    const char *p;
    static const char prefix[] = "+QIOPEN: ";
    if (line == NULL || strncmp(line, prefix, sizeof(prefix) - 1U) != 0)
        return false;
    p = line + sizeof(prefix) - 1U;
    if (!parse_uint_field(&p, EC800M_CH_MAX - 1U, channel) || *p++ != ',')
        return false;
    return parse_uint_field(&p, 65535U, error) && *p == '\0';
}

/* "+QNTP: <err>,\"yyyy/MM/dd,hh:mm:ss[+-]zz\"" — err=0 means the quoted
 * local time is valid; the trailing signed field is a quarter-hour-east-of-
 * UTC offset. Hand-rolled (no sscanf/atof/strtod: forbidden by
 * tools/libc_parser_guard.py). */
static bool parse_qntp(const char *line, unsigned *year, unsigned *month,
                       unsigned *day, unsigned *hour, unsigned *minute,
                       unsigned *second, int *tz_quarter)
{
    const char *p;
    unsigned err;
    unsigned tzmag = 0U;
    bool tz_neg = false;
    static const char prefix[] = "+QNTP: ";
    if (line == NULL || strncmp(line, prefix, sizeof(prefix) - 1U) != 0)
        return false;
    p = line + sizeof(prefix) - 1U;
    if (!parse_uint_field(&p, 65535U, &err) || *p++ != ',' || err != 0U)
        return false;
    if (*p++ != '"') return false;
    if (!parse_uint_field(&p, 9999U, year) || *p++ != '/') return false;
    if (!parse_uint_field(&p, 12U, month) || *p++ != '/') return false;
    if (!parse_uint_field(&p, 31U, day) || *p++ != ',') return false;
    if (!parse_uint_field(&p, 23U, hour) || *p++ != ':') return false;
    if (!parse_uint_field(&p, 59U, minute) || *p++ != ':') return false;
    if (!parse_uint_field(&p, 59U, second)) return false;
    if (*p == '+' || *p == '-') {
        tz_neg = (*p == '-');
        ++p;
        if (!parse_uint_field(&p, 96U, &tzmag)) return false;
    }
    if (*p != '"') return false;
    if (*year < 2024U || *month == 0U || *day == 0U) return false;
    *tz_quarter = tz_neg ? -(int)tzmag : (int)tzmag;
    return true;
}

/* Shift (hour,minute) on (year,month,day) by a signed minute offset,
 * carrying at most one day in either direction (bounded by a realistic
 * +-14h timezone offset). Mirrors the calendar rollover already used by
 * gps_advance_last_trusted_seconds(). */
static void ntp_shift_minutes(uint16_t *year, uint8_t *month, uint8_t *day,
                              uint8_t *hour, uint8_t *minute, int offset_min)
{
    static const uint8_t days_in_month[13] =
        { 0U, 31U, 28U, 31U, 30U, 31U, 30U, 31U, 31U, 30U, 31U, 30U, 31U };
    int total = (int)*hour * 60 + (int)*minute + offset_min;
    int day_delta = 0;
    bool leap;
    uint8_t dim;
    while (total < 0) { total += 1440; --day_delta; }
    while (total >= 1440) { total -= 1440; ++day_delta; }
    *hour = (uint8_t)(total / 60);
    *minute = (uint8_t)(total % 60);
    while (day_delta > 0) {
        --day_delta;
        leap = (*year % 4U == 0U && *year % 100U != 0U) || (*year % 400U == 0U);
        dim = *month == 2U && leap ? 29U : days_in_month[*month];
        if (++(*day) > dim) {
            *day = 1U;
            if (++(*month) > 12U) { *month = 1U; ++(*year); }
        }
    }
    while (day_delta < 0) {
        ++day_delta;
        if (--(*day) == 0U) {
            if (--(*month) == 0U) { *month = 12U; --(*year); }
            leap = (*year % 4U == 0U && *year % 100U != 0U) || (*year % 400U == 0U);
            *day = *month == 2U && leap ? 29U : days_in_month[*month];
        }
    }
}

static bool is_deferred_urc(const char *line)
{
    return line && (strncmp(line, "+QIURC:", 7) == 0 ||
                    strncmp(line, "+QIOPEN:", 8) == 0);
}

static void defer_urc(const char *line)
{
    char *slot;
    if (!line || !is_deferred_urc(line) ||
        s_deferred_urc_count >= AT_DEFERRED_URC_MAX) return;
    slot = s_deferred_urc[s_deferred_urc_tail];
    (void)strncpy(slot, line, AT_LINE_MAX - 1U);
    slot[AT_LINE_MAX - 1U] = '\0';
    s_deferred_urc_tail = (uint8_t)((s_deferred_urc_tail + 1U) % AT_DEFERRED_URC_MAX);
    ++s_deferred_urc_count;
}

static void process_deferred_urc_one(void)
{
    char line[AT_LINE_MAX];

    if (s_at_owner != AT_OWNER_NONE || s_deferred_urc_count == 0U ||
        s_deferred_urc_processing) return;
    s_deferred_urc_processing = true;
    (void)strncpy(line, s_deferred_urc[s_deferred_urc_head], sizeof(line) - 1U);
    line[sizeof(line) - 1U] = '\0';
    s_deferred_urc_head = (uint8_t)((s_deferred_urc_head + 1U) % AT_DEFERRED_URC_MAX);
    --s_deferred_urc_count;
    process_urc(line);
    s_deferred_urc_processing = false;
}

static void process_rx_line(void)
{
    bool cmt_header;
    bool cmt_body;

    s_line_buf[s_line_len] = '\0';
    udp_note_line(s_line_buf);
    if (s_line_len == 0U) {
        if (s_cmt_body_pending) {
            sms_process_urc(s_line_buf);
            s_cmt_body_pending = false;
        }
        return;
    }

    cmt_header = strncmp(s_line_buf, "+CMT:", 5) == 0;
    cmt_body = s_cmt_body_pending;
    if ((cmt_header || cmt_body) && s_at_resp_pos_ref != NULL)
        *s_at_resp_pos_ref = s_at_resp_line_start;
    if (cmt_header || cmt_body)
        sms_process_urc(s_line_buf);

    /* +CMT is a two-line URC.  Consume both lines here so a blocking AT
     * transaction cannot mistake the SMS body for an AT response/URC. */
    if (cmt_header) {
        s_cmt_body_pending = true;
        return;
    }
    if (cmt_body) {
        s_cmt_body_pending = false;
        return;
    }

    /* Socket URCs may trigger blocking AT commands (QIRD/QICLOSE).  Always
     * queue them until the current line has been fully retired, otherwise a
     * nested receive wait reuses s_line_buf/s_line_len while they still hold
     * this URC. */
    if (is_deferred_urc(s_line_buf))
        defer_urc(s_line_buf);
    else
        process_urc(s_line_buf);
}

static void process_rx_byte(char c)
{
    /* UDP QIRD payload is length-delimited binary data and cannot be parsed
     * reliably through the line accumulator.  Copy it byte-for-byte into the
     * caller's bounded buffer while the cooperative transaction owns QIRD. */
    if (s_udp_txn_state == UDP_TXN_WAIT_QIRD && !s_udp_qird_done) {
        static const uint8_t qird_tail[] = "\r\nOK\r\n";
        if (s_udp_resp_len < s_udp_rx_cap)
            s_udp_rx[s_udp_resp_len++] = (uint8_t)c;
        else
            s_udp_qird_overflow = true;
        if (!s_udp_qird_overflow && s_udp_resp_len >= sizeof(qird_tail) - 1U &&
            memcmp(&s_udp_rx[s_udp_resp_len - (sizeof(qird_tail) - 1U)],
                   qird_tail, sizeof(qird_tail) - 1U) == 0) {
            const uint8_t *payload = NULL;
            uint16_t payload_len = 0U;
            if (ec800m_parse_qird_response(s_udp_rx, s_udp_resp_len,
                                           &payload, &payload_len)) {
                s_udp_qird_received = payload_len;
                s_udp_qird_done = true;
            }
        }
    }
    if (c == '>' && s_sms_tx_state == SMS_TX_WAIT_PROMPT &&
        s_line_len == 0U && s_sms_prompt_line_start) {
        s_sms_prompt = true;
    }
    if (c == '>' && s_udp_txn_state == UDP_TXN_WAIT_PROMPT)
        s_udp_prompt = true;
    if (c == '\r') return;
    if (c == '\n') {
        process_rx_line();
        s_line_len = 0U;
        s_sms_prompt_line_start = true;
        s_cmt_line_active = false;
        return;
    }
    if (s_cmt_body_pending) s_cmt_line_active = true;
    if (!s_cmt_line_active && s_line_len == 4U &&
        memcmp(s_line_buf, "+CMT", 4U) == 0 && c == ':')
        s_cmt_line_active = true;
    if (c != ' ' && c != '>') s_sms_prompt_line_start = false;
    if (s_line_len < AT_LINE_MAX - 1U)
        s_line_buf[s_line_len++] = c;
}

/* AT command/URC lines are observed by the normal RX pump.  This function is
 * intentionally side-effect free apart from transaction flags; it never
 * sends another command from inside the parser (avoiding nested waits). */
static void udp_note_line(const char *line)
{
    unsigned channel;
    unsigned error;
    if (!udp_txn_active() || line == NULL) return;
    if (strcmp(line, "OK") == 0 || strcmp(line, "SEND OK") == 0)
        s_udp_cmd_ok = true;
    else if (strcmp(line, "ERROR") == 0 || strncmp(line, "+CME ERROR", 10U) == 0)
        s_udp_cmd_error = true;
    if (parse_qiopen(line, &channel, &error) && channel == EC800M_CH_OTA) {
        if (error == 0U) s_udp_open_urc = true;
        else s_udp_cmd_error = true;
    }
    if (parse_prefixed_uint(line, "+QIURC: \"recv\",",
                            EC800M_CH_MAX - 1U, &channel) &&
        channel == EC800M_CH_OTA)
        s_udp_recv_urc = true;
}

static bool at_send_wait_owned(const char *cmd, const char *expect,
                               uint32_t timeout_ms)
{
    memset(s_at_resp, 0, sizeof(s_at_resp));
    s_at_resp_len = 0;

#if EC800M_RX_ECHO
    if (cmd[0]) dbg_printf(">> %s\r\n", cmd);
#endif
    if (cmd[0]) {
        if (!usart_send_str(cmd) || !usart_send_str("\r\n")) return false;
    }

    uint32_t start = TICK_MS();
    uint16_t resp_pos = 0;

    while ((TICK_MS() - start) < timeout_ms) {
        IWDG_ReloadKey();
        uint16_t dma_remain = DMA_GetCurrDataCounter(DMA_CH5);
        uint16_t s_rx_wr = EC800M_RX_BUF_SIZE - dma_remain;

        while (s_rx_rd != s_rx_wr) {
            uint8_t c = EC800M_RX_BUF[s_rx_rd];
            s_rx_rd = (uint16_t)((s_rx_rd + 1) % EC800M_RX_BUF_SIZE);
#if EC800M_RX_ECHO
            dbg_putchar((char)c);
#endif
            bool cmt_byte = s_cmt_line_active || s_cmt_body_pending;
            if (s_line_len == 0U)
                s_at_resp_line_start = resp_pos;
            if (!cmt_byte && resp_pos < AT_RESP_MAX - 1)
                s_at_resp[resp_pos++] = (char)c;
            s_at_resp_pos_ref = &resp_pos;
            process_rx_byte((char)c);
            /* The first four +CMT header bytes are provisional.  Once the
             * colon confirms the header, remove that whole line from the
             * AT-response matcher and suppress the rest of header/body. */
            if (!cmt_byte && s_cmt_line_active)
                resp_pos = s_at_resp_line_start;
        }
        s_at_resp_pos_ref = NULL;
        s_at_resp_len = resp_pos;
        s_at_resp[resp_pos] = '\0';
        if (strcmp(expect, "OK") == 0) {
            ec800m_at_end_t end = ec800m_at_response_end(s_at_resp, resp_pos);
            if (end == EC800M_AT_OK) return true;
            if (end == EC800M_AT_ERROR) return false;
        } else {
            if (expect[0] && strstr(s_at_resp, expect)) return true;
            if (ec800m_at_response_end(s_at_resp, resp_pos) == EC800M_AT_ERROR)
                return false;
        }
    }
    return false;
}

/* QISEND returns a bare '>' prompt without requiring CR/LF.  Keep this
 * separate from line response matching so payload transmission cannot be
 * delayed by a missing line terminator. */
static bool at_wait_prompt_owned(const char *cmd, uint32_t timeout_ms)
{
    if (!usart_send_str(cmd) || !usart_send_str("\r\n")) return false;

    uint32_t start = TICK_MS();
    while ((TICK_MS() - start) < timeout_ms) {
        IWDG_ReloadKey();
        uint16_t dma_remain = DMA_GetCurrDataCounter(DMA_CH5);
        uint16_t rx_wr = EC800M_RX_BUF_SIZE - dma_remain;

        while (s_rx_rd != rx_wr) {
            char c = (char)EC800M_RX_BUF[s_rx_rd];
            s_rx_rd = (uint16_t)((s_rx_rd + 1U) % EC800M_RX_BUF_SIZE);
#if EC800M_RX_ECHO
            dbg_putchar(c);
#endif
            if (c == '>') {
                process_rx_byte(c);
                return true;
            }
            process_rx_byte(c);
        }
    }
    return false;
}

static bool at_send_wait(const char *cmd, const char *expect,
                         uint32_t timeout_ms)
{
    bool ok;
    if (!at_owner_acquire(AT_OWNER_BLOCKING)) return false;
    ok = at_send_wait_owned(cmd, expect, timeout_ms);
    at_owner_release(AT_OWNER_BLOCKING);
    /* URCs observed while the owner was held can now start their own AT work. */
    process_deferred_urc_one();
    return ok;
}

/* ── Power control ────────────────────────────────────────────────────────── */

/* Poll to detect if EC800M is already online; returns true if AT responded */
static bool ec800m_is_alive(uint32_t timeout_ms)
{
    bool alive = false;
    if (!at_owner_acquire(AT_OWNER_BLOCKING)) return false;
    /* Flush receive buffer, but never let a stuck status bit spin forever. */
    uint32_t flush_deadline = TICK_MS() + timeout_ms;
    while (USART_GetFlagStatus(EC800M_UART, USART_FLAG_RXDNE) != RESET) {
        IWDG_ReloadKey();
        if ((int32_t)(TICK_MS() - flush_deadline) >= 0) {
            at_owner_release(AT_OWNER_BLOCKING);
            return false;
        }
        USART_ReceiveData(EC800M_UART);
    }

    if (!usart_send_str("AT\r\n")) {
        at_owner_release(AT_OWNER_BLOCKING);
        return false;
    }

    uint32_t t0 = TICK_MS();
    char buf[16]; uint8_t pos = 0;
    while (TICK_MS() - t0 < timeout_ms) {
        IWDG_ReloadKey();
        if (USART_GetFlagStatus(EC800M_UART, USART_FLAG_RXDNE) != RESET) {
            char c = (char)USART_ReceiveData(EC800M_UART);
            if (pos < 15) buf[pos++] = c;
            buf[pos] = '\0';
            if (strstr(buf, "OK") || strstr(buf, "AT")) { alive = true; break; }
        }
    }
    at_owner_release(AT_OWNER_BLOCKING);
    return alive;
}

void ec800m_power_on(void)
{
    /* 1. Ensure VBAT power enable */
    GPIO_SetBits(EC800M_POWER_EN_PORT, EC800M_POWER_EN_PIN);
    delay_ms(50);

    /* 2. Check if already online */
    if (ec800m_is_alive(1000)) {
        return;
    }

    /* 3. PA8=LOW → pull PWRKEY low → trigger power-on (≥700ms per datasheet) */
    GPIO_ResetBits(EC800M_PWRKEY_PORT, EC800M_PWRKEY_PIN);
    delay_ms(750);
    GPIO_SetBits(EC800M_PWRKEY_PORT, EC800M_PWRKEY_PIN);
    delay_ms(10000);  /* UART ready ≥10s after PWRKEY release per datasheet Fig.12 */
}

void ec800m_power_off(void)
{
    if (s_sms_tx_state != SMS_TX_IDLE) { s_sms_tx_state=SMS_TX_IDLE; s_at_owner=AT_OWNER_NONE; sms_send_complete(false); }
    at_send_wait("AT+QPOWD=0", "POWERED DOWN", 5000);
    GPIO_SetBits(EC800M_PWRKEY_PORT, EC800M_PWRKEY_PIN);  /* PA8=HIGH = idle */
    s_state = EC800M_STATE_OFF;
}

void ec800m_reset(void)
{
    if (s_sms_tx_state != SMS_TX_IDLE) { s_sms_tx_state = SMS_TX_IDLE; s_sms_prompt = false; s_at_owner = AT_OWNER_NONE; sms_send_complete(false); }
    ec800m_power_off();
    delay_ms(1000);
    ec800m_power_on();
    s_state = EC800M_STATE_BOOTING;
    s_state_enter_ms = TICK_MS();
    s_init_step = 0;
    s_iccid_attempts = 0U;
    s_sim_identity_ready = false;
    s_reg_status = -1;
    s_failure = EC800M_FAILURE_NONE;
}

/* ── Init sequence steps ──────────────────────────────────────────────────── */
static const char *s_init_cmds[] = {
    "ATE0",
    "AT+QURCCFG=\"urcport\",\"uart1\"",
    "AT+CMGF=1",
    "AT+CNMI=2,2,0,0,0",
    "AT+CTZU=3",
    NULL
};

static void state_machine_init(void)
{
    bool ok;
    switch (s_init_step) {
    case 0: /* basic AT test */
        ok = at_send_wait("AT", "OK", 1000);
        if (!ok) {
            if (TICK_MS() - s_state_enter_ms > 15000)
                ec800m_reset();
            return;
        }
        s_init_step++;
        break;
    case 1 ... 5: {
        const char *cmd = s_init_cmds[s_init_step - 1];
        at_send_wait(cmd, "OK", 2000);
        s_init_step++;
        break;
    }
    case 6: /* read IMEI */
        if (at_send_wait("AT+CGSN", "OK", 2000)) {
            /* search directly for 15 consecutive digits, no newline dependency */
            char *p = s_at_resp;
            while (*p) {
                if (*p >= '0' && *p <= '9') {
                    char *start = p;
                    uint8_t n = 0;
                    while (*p >= '0' && *p <= '9') { n++; p++; }
                    if (n == 15) {
                        memcpy(s_imei, start, 15);
                        s_imei[15] = '\0';
                        break;
                    }
                } else {
                    p++;
                }
            }
        }
        s_init_step++;
        break;
    case 7: /* ICCID */
        ok = at_send_wait("AT+QCCID", "OK", 2000) &&
             parse_iccid_response(s_at_resp, s_iccid);
        if (iccid_retry_should_advance(ok, &s_iccid_attempts))
            s_init_step++;
        break;
    case 8:
        s_state = EC800M_STATE_SIM_CHECK;
        s_state_enter_ms = TICK_MS();
        s_iccid_attempts = 0U;
        s_sim_identity_ready = false;
        break;
    }
}

static void state_machine_sim(void)
{
    bool at_ok, parsed;
    if (!s_sim_identity_ready) {
        if (at_send_wait("AT+CIMI", "OK", 2000)) {
            s_sim_identity_ready = true;
            s_failure = EC800M_FAILURE_NONE;
        } else if (TICK_MS() - s_state_enter_ms > 30000) {
            s_failure = EC800M_FAILURE_SIM_QUERY;
            s_state = EC800M_STATE_ERROR;
            return;
        } else {
            s_failure = EC800M_FAILURE_SIM_QUERY;
            return;
        }
    }

    if (iccid_refresh_required(s_sim_identity_ready, s_iccid)) {
        at_ok = at_send_wait("AT+QCCID", "OK", 2000);
        parsed = at_ok && parse_iccid_response(s_at_resp, s_iccid);
        dbg_printf("[4G] iccid query phase=SIM attempt=%u at=%u resp=%u parsed=%u\r\n",
                   (unsigned)s_iccid_attempts + 1U, at_ok ? 1U : 0U,
                   (unsigned)s_at_resp_len, parsed ? 1U : 0U);
        if (!iccid_retry_should_advance(parsed, &s_iccid_attempts)) return;
    }

    dbg_printf("[4G] identity ready imei_len=%u iccid_len=%u\r\n",
               (unsigned)strlen(s_imei), (unsigned)strlen(s_iccid));
    s_failure = EC800M_FAILURE_NONE;
    s_state = EC800M_STATE_NETWORK_REG;
    s_state_enter_ms = TICK_MS();
}

static void state_machine_netreg(void)
{
    /* Try LTE first, fall back to 2G/3G */
    bool reg = false;
    int status = -1;
    s_reg_status = -1;
    if (at_send_wait("AT+CEREG?", "OK", 2000))
        (void)ec800m_parse_reg_status(s_at_resp, "+CEREG:", &status);
    if (status < 0 && at_send_wait("AT+CGREG?", "OK", 2000))
        (void)ec800m_parse_reg_status(s_at_resp, "+CGREG:", &status);
    s_reg_status = status;
    reg = status == 1 || status == 5;

    if (reg) {
        s_failure = EC800M_FAILURE_NONE;
        s_state = EC800M_STATE_PDP_ACTIVE;
        s_state_enter_ms = TICK_MS();
    } else if (TICK_MS() - s_state_enter_ms > 60000) {
        s_failure = EC800M_FAILURE_NETREG_QUERY;
        ec800m_reset();
    } else {
        s_failure = EC800M_FAILURE_NETREG_QUERY;
    }
}

static void state_machine_pdp(void)
{
    bool activate_ok;
    /* activate PDP context 1 */
    activate_ok = at_send_wait("AT+QIACT=1", "OK", 10000);
    if (!activate_ok) s_failure = EC800M_FAILURE_PDP_ACTIVATE;
    if (at_send_wait("AT+QIACT?", "+QIACT:", 3000)) {
        s_failure = EC800M_FAILURE_NONE;
        s_state = EC800M_STATE_READY;
        s_state_enter_ms = TICK_MS();
        dbg_printf("[4G] ready\r\n");
    } else if (TICK_MS() - s_state_enter_ms > 30000) {
        s_failure = EC800M_FAILURE_PDP_QUERY;
        s_state = EC800M_STATE_NETWORK_REG;
        s_state_enter_ms = TICK_MS();
    } else if (activate_ok) {
        s_failure = EC800M_FAILURE_PDP_QUERY;
    }
}

/* ── URC / receive processing ─────────────────────────────────────────────── */
static void process_urc(const char *line)
{
    unsigned ch;
    if (s_at_owner != AT_OWNER_NONE && is_deferred_urc(line)) {
        defer_urc(line);
        return;
    }
    /* +QIOPEN: ch,0  → open success */
    /* +QIOPEN: ch,err */
    unsigned qiopen_ch, qiopen_err;
    sms_process_urc(line);
    if (s_at_owner == AT_OWNER_SMS &&
        ((s_sms_tx_state == SMS_TX_WAIT_RESULT &&
          (strncmp(line, "+CMGS:", 6) == 0 || strncmp(line, "+QCMGS:", 7) == 0)) ||
         (s_sms_tx_state != SMS_TX_IDLE &&
          (strncmp(line, "+CMS ERROR:", 11) == 0 || strcmp(line, "ERROR") == 0)))) {
        bool sent = strncmp(line, "+CMGS:", 6) == 0 ||
                    strncmp(line, "+QCMGS:", 7) == 0;
        /* Each concatenated part is acknowledged separately; the reply is only
         * complete once the last one is accepted. */
        if (sent && (uint8_t)(s_sms_seg_index + 1U) < s_sms_seg_total) {
            ++s_sms_seg_index;
            s_sms_tx_state = SMS_TX_QUEUED;
            at_owner_release(AT_OWNER_SMS);
        } else {
            s_sms_tx_state = SMS_TX_IDLE; at_owner_release(AT_OWNER_SMS);
            sms_send_complete(sent);
        }
    } else if (s_sms_tx_state != SMS_TX_IDLE && strncmp(line, "+CMS ERROR:", 11) == 0) {
        s_sms_tx_state = SMS_TX_IDLE; at_owner_release(AT_OWNER_SMS);
        sms_send_complete(false);
    }
    if (parse_qiopen(line, &qiopen_ch, &qiopen_err)) {
        if (qiopen_err == 0) {
            s_tcp[qiopen_ch].state = TCP_STATE_OPEN;
        } else {
            char cmd[32];
            snprintf(cmd, sizeof(cmd), "AT+QICLOSE=%d", qiopen_ch);
            at_send_wait(cmd, "OK", 3000);
            /* flush DMA buffer after close to discard any trailing URCs */
            delay_ms(200);
            uint16_t dma_remain = DMA_GetCurrDataCounter(DMA_CH5);
            s_rx_rd = EC800M_RX_BUF_SIZE - dma_remain;
            s_tcp[qiopen_ch].state = TCP_STATE_CLOSED;
        }
        return;
    }
    /* +QIURC: "recv",ch */
    if (parse_prefixed_uint(line, "+QIURC: \"recv\",",
                            EC800M_CH_MAX - 1U, &ch)) {
        char cmd[32];
        dbg_printf("[4G-RX] ch=%u event=recv\r\n", (unsigned int)ch);
        snprintf(cmd, sizeof(cmd), "AT+QIRD=%d,1200", ch);
        if (at_send_wait(cmd, "OK", 2000)) {
            const uint8_t *data_start;
            uint16_t dlen;
            ec800m_qird_diag_t diag;
            if (ec800m_parse_qird_response_diag((const uint8_t *)s_at_resp,
                                                 s_at_resp_len,
                                                 &data_start, &dlen,
                                                 &diag) && dlen > 0U) {
                dbg_printf("[4G-RX] ch=%u qird=%u\r\n",
                           (unsigned int)ch, (unsigned int)dlen);
                if (ch == EC800M_CH_OTA && s_ota_recv_cb)
                    s_ota_recv_cb((uint8_t)ch, data_start, dlen);
                else if (ch == EC800M_CH_AGPS && s_agnss_recv_cb)
                    s_agnss_recv_cb((uint8_t)ch, data_start, dlen);
                else if (s_recv_cb)
                    s_recv_cb((uint8_t)ch, data_start, dlen);
            } else
                dbg_printf("[4G-RX] ch=%u qird_fail=FORMAT stage=%u total=%u hdr=%d decl=%u remain=%u tail=%02X\r\n",
                           (unsigned int)ch, (unsigned int)diag.stage,
                           (unsigned int)diag.total_length, (int)diag.header_offset,
                           (unsigned int)diag.declared_length,
                           (unsigned int)diag.remaining_length,
                           (unsigned int)diag.tail_mask);
        } else {
            dbg_printf("[4G-RX] ch=%u qird_fail=AT\r\n", (unsigned int)ch);
        }
        return;
    }
    /* +QIURC: "closed",ch */
    if (parse_prefixed_uint(line, "+QIURC: \"closed\",",
                            EC800M_CH_MAX - 1U, &ch)) {
        s_tcp[ch].state = TCP_STATE_CLOSED;
        return;
    }
    /* +QIURC: "pdpdeact",1 */
    if (strstr(line, "+QIURC: \"pdpdeact\"")) {
        s_reg_status = -1;
        s_state = EC800M_STATE_NETWORK_REG;
        s_state_enter_ms = TICK_MS();
        for (int i = 0; i < EC800M_CH_MAX; i++)
            s_tcp[i].state = TCP_STATE_CLOSED;
    }
    /* +CSQ */
    if (strncmp(line, "+CSQ: ", 6U) == 0) {
        const char *p = line + 6U;
        unsigned csq;
        if (parse_uint_field(&p, 99U, &csq) && *p++ == ',' &&
            *p >= '0' && *p <= '9') {
            unsigned ber;
            if (parse_uint_field(&p, 99U, &ber) && *p == '\0') {
                (void)ber;
                s_csq = (int)csq;
            }
        }
        return;
    }
}

/* ── Drain RX ring and process complete lines (URCs) ─────────────────────── */
static void drain_rx(void)
{
    /* DMA mode: calculate write pointer from DMA counter */
    uint16_t dma_remain = DMA_GetCurrDataCounter(DMA_CH5);
    uint16_t s_rx_wr = EC800M_RX_BUF_SIZE - dma_remain;

    while (s_rx_rd != s_rx_wr) {
        char c = (char)EC800M_RX_BUF[s_rx_rd];
        s_rx_rd = (uint16_t)((s_rx_rd + 1) % EC800M_RX_BUF_SIZE);

#if EC800M_RX_ECHO
        dbg_putchar(c);
#endif
        process_rx_byte(c);
    }
}

/* ── Public API ───────────────────────────────────────────────────────────── */
void ec800m_init(void)
{
    if (s_sms_tx_state != SMS_TX_IDLE) sms_send_complete(false);
    s_sms_tx_state=SMS_TX_IDLE; s_at_owner=AT_OWNER_NONE; s_sms_prompt=false;
    s_line_len = 0U; s_sms_prompt_line_start = true; s_cmt_body_pending = false; s_cmt_line_active = false;
    s_deferred_urc_head = 0U; s_deferred_urc_tail = 0U; s_deferred_urc_count = 0U;
    s_deferred_urc_processing = false;
    s_reg_status = -1;
    s_failure = EC800M_FAILURE_NONE;
    s_last_diag_ms = 0U;
    rx_irq_init();
    memset(s_tcp, 0, sizeof(s_tcp));
    s_state = EC800M_STATE_BOOTING;
    s_state_enter_ms = TICK_MS();
    s_init_step = 0;
    s_iccid_attempts = 0U;
    s_sim_identity_ready = false;
    ec800m_power_on();
}

void ec800m_process(void)
{
    drain_rx();
    sms_tx_process();
    process_deferred_urc_one();

    switch (s_state) {
    case EC800M_STATE_BOOTING:
        if (TICK_MS() - s_state_enter_ms > 5000) {
            s_state = EC800M_STATE_INIT;
            s_state_enter_ms = TICK_MS();
        }
        break;
    case EC800M_STATE_INIT:
        state_machine_init();
        break;
    case EC800M_STATE_SIM_CHECK:
        state_machine_sim();
        break;
    case EC800M_STATE_NETWORK_REG:
        state_machine_netreg();
        break;
    case EC800M_STATE_PDP_ACTIVE:
        state_machine_pdp();
        break;
    case EC800M_STATE_READY:
        /* CSQ: request every 30s, response comes as URC "+CSQ:" parsed in process_urc */
        if (TICK_MS() - s_state_enter_ms > 30000 &&
            (TICK_MS() % 30000) > 29900) {
            if (s_at_owner == AT_OWNER_NONE) (void)at_send_wait("AT+CSQ", "+CSQ:", 1000);
        }
        break;
    case EC800M_STATE_ERROR:
        if (TICK_MS() - s_state_enter_ms > 60000) ec800m_reset();
        break;
    default: break;
    }
    if (s_state != EC800M_STATE_READY &&
        TICK_MS() - s_last_diag_ms >= EC800M_DIAG_INTERVAL_MS) {
        s_last_diag_ms = TICK_MS();
        dbg_printf("[4G] state=%s reason=%s reg=%d\r\n",
                   ec800m_state_name(s_state), ec800m_failure_name(s_failure),
                   s_reg_status);
    }
}

ec800m_state_t ec800m_get_state(void) { return s_state; }
ec800m_failure_t ec800m_get_failure(void) { return s_failure; }
int ec800m_get_reg_status(void) { return s_reg_status; }
const char *ec800m_state_name(ec800m_state_t state)
{
    static const char *const names[] = {
        "OFF", "BOOTING", "INIT", "SIM", "NETREG", "PDP", "READY", "ERROR"
    };
    return (unsigned int)state <= (unsigned int)EC800M_STATE_ERROR ? names[state] : "UNKNOWN";
}
const char *ec800m_failure_name(ec800m_failure_t failure)
{
    static const char *const names[] = {
        "NONE", "SIM_QUERY", "NETREG_QUERY", "PDP_ACTIVATE", "PDP_QUERY"
    };
    return (unsigned int)failure <= (unsigned int)EC800M_FAILURE_PDP_QUERY ? names[failure] : "UNKNOWN";
}
bool ec800m_is_ready(void)            { return s_state == EC800M_STATE_READY; }

#ifdef EC800M_HOST_TEST
/* Host-only controls used by the production-chain harness.  They are not
 * part of the target API or firmware build. */
void ec800m_test_set_state(ec800m_state_t state) { s_state = state; }
void ec800m_test_set_imei(const char *imei)
{
    if (imei == NULL) return;
    (void)strncpy(s_imei, imei, sizeof(s_imei) - 1U);
    s_imei[sizeof(s_imei) - 1U] = '\0';
}
void ec800m_test_set_tcp_open(uint8_t ch)
{
    if (ch < EC800M_CH_MAX) s_tcp[ch].state = TCP_STATE_OPEN;
}
bool ec800m_test_parse_iccid(const char *response, char out[22])
{ return parse_iccid_response(response, out); }
bool ec800m_test_iccid_retry_should_advance(bool parsed, uint8_t *attempts)
{ return iccid_retry_should_advance(parsed, attempts); }
bool ec800m_test_iccid_refresh_required(bool sim_identity_ready,
                                        const char *iccid)
{ return iccid_refresh_required(sim_identity_ready, iccid); }
bool ec800m_test_parse_qntp(const char *line, unsigned *year, unsigned *month,
                            unsigned *day, unsigned *hour, unsigned *minute,
                            unsigned *second, int *tz_quarter)
{ return parse_qntp(line, year, month, day, hour, minute, second, tz_quarter); }
void ec800m_test_shift_minutes(uint16_t *year, uint8_t *month, uint8_t *day,
                               uint8_t *hour, uint8_t *minute, int offset_min)
{ ntp_shift_minutes(year, month, day, hour, minute, offset_min); }
#endif

static void sms_tx_process(void)
{
    char command[64];
    if (!ec800m_is_ready()) return;
    if (s_sms_tx_state == SMS_TX_QUEUED) {
        if (!at_owner_acquire(AT_OWNER_SMS)) return;
        if (s_sms_seg_total > 1U) {
            /* AT+CMGS cannot segment; a concatenated message must go out one
             * part at a time through AT+QCMGS with a shared <uid>. */
            (void)snprintf(command, sizeof command,
                           "AT+QCMGS=\"%s\",%u,%u,%u", s_sms_phone,
                           (unsigned)s_sms_uid,
                           (unsigned)(s_sms_seg_index + 1U),
                           (unsigned)s_sms_seg_total);
        } else {
            (void)snprintf(command, sizeof command, "AT+CMGS=\"%s\"", s_sms_phone);
        }
        if (!usart_send_buf((const uint8_t *)command, (uint16_t)strlen(command)) || !usart_send_buf((const uint8_t *)"\r\n",2U)) { s_sms_tx_state=SMS_TX_IDLE; at_owner_release(AT_OWNER_SMS); sms_send_complete(false); return; }
        s_sms_prompt = false; s_sms_prompt_line_start = true; s_sms_tx_state = SMS_TX_WAIT_PROMPT; s_sms_deadline_ms = TICK_MS() + 5000U;
    } else if (s_sms_tx_state == SMS_TX_WAIT_PROMPT && s_sms_prompt) {
        uint16_t offset = (uint16_t)(s_sms_seg_index * EC800M_SMS_SEGMENT_MAX);
        uint16_t remaining = (uint16_t)(s_sms_len - offset);
        uint16_t count = remaining > EC800M_SMS_SEGMENT_MAX ?
                         EC800M_SMS_SEGMENT_MAX : remaining;
        if (!usart_send_buf((const uint8_t *)&s_sms_text[offset], count) || !usart_send_buf((const uint8_t *)"\x1A", 1U)) { s_sms_tx_state=SMS_TX_IDLE; at_owner_release(AT_OWNER_SMS); sms_send_complete(false); return; }
        s_sms_tx_state = SMS_TX_WAIT_RESULT; s_sms_deadline_ms = TICK_MS() + 30000U;
    } else if (s_sms_tx_state != SMS_TX_IDLE && s_sms_tx_state != SMS_TX_QUEUED &&
               (int32_t)(TICK_MS() - s_sms_deadline_ms) >= 0) {
        s_sms_tx_state = SMS_TX_IDLE; at_owner_release(AT_OWNER_SMS);
        sms_send_complete(false);
    }
}

int ec800m_sms_send(const char *phone, const char *text)
{
    size_t n;
    if (!phone || !text || !ec800m_is_ready()) return -1;
    if (s_sms_tx_state != SMS_TX_IDLE || s_at_owner != AT_OWNER_NONE) return -2;
    n = strlen(text);
    if (strlen(phone) == 0U || strlen(phone) >= 20U || n == 0U ||
        n >= EC800M_SMS_TEXT_MAX) return -3;
    (void)strcpy(s_sms_phone, phone); (void)strcpy(s_sms_text, text);
    s_sms_len = (uint16_t)n;
    s_sms_seg_total = (uint8_t)((n + EC800M_SMS_SEGMENT_MAX - 1U) /
                                EC800M_SMS_SEGMENT_MAX);
    s_sms_seg_index = 0U;
    /* A concatenated message needs a reference shared by all of its parts and
     * distinct from the previous message's; the low byte of a counter is
     * enough for the one-reply-at-a-time traffic this device sends. */
    if (s_sms_seg_total > 1U) ++s_sms_uid;
    s_sms_tx_state = SMS_TX_QUEUED;
    return 0;
}

int ec800m_tcp_open(uint8_t ch, const char *ip, uint16_t port)
{
    if (ch >= EC800M_CH_MAX || !ec800m_is_ready()) return -1;
    if (s_tcp[ch].state == TCP_STATE_OPEN) return 0;

    char cmd[128];
    snprintf(cmd, sizeof(cmd),
             "AT+QIOPEN=1,%d,\"TCP\",\"%s\",%u,0,0", ch, ip, port);
    s_tcp[ch].state = TCP_STATE_OPENING;
    strncpy(s_tcp[ch].ip, ip, sizeof(s_tcp[ch].ip)-1);
    s_tcp[ch].port = port;

    if (!at_send_wait(cmd, "OK", 5000)) {
        s_tcp[ch].state = TCP_STATE_ERROR;
        return -1;
    }
    /* +QIOPEN URC arrives asynchronously via drain_rx */
    return 0;
}

static bool s_tcp_send_ambiguous = false;

/* Echo the last AT response on the debug UART with CR/LF and any non-printable
 * byte escaped, so a modem reply can be read back from a field capture without
 * the embedded newlines breaking up the surrounding log line. */
static void at_dump_response(void)
{
    uint16_t i;
    for (i = 0U; i < s_at_resp_len && i < AT_RESP_MAX; ++i) {
        char c = s_at_resp[i];
        if (c == '\0') break;
        if (c == '\r') dbg_printf("\\r");
        else if (c == '\n') dbg_printf("\\n");
        else if (c >= 0x20 && c < 0x7f) dbg_printf("%c", c);
        else dbg_printf("\\x%02x", (unsigned)(uint8_t)c);
    }
}

bool ec800m_tcp_send_was_ambiguous(void) { return s_tcp_send_ambiguous; }
void ec800m_tcp_send_clear_ambiguous(void) { s_tcp_send_ambiguous = false; }

int ec800m_tcp_send(uint8_t ch, const uint8_t *data, uint16_t len)
{
    int result = -1;
    s_tcp_send_ambiguous = false;
    if (ch >= EC800M_CH_MAX || s_tcp[ch].state != TCP_STATE_OPEN) return -1;
    if (!data || len == 0U || !at_owner_acquire(AT_OWNER_TCP)) return -2;

    char cmd[32];
    snprintf(cmd, sizeof(cmd), "AT+QISEND=%d,%u", ch, len);
    dbg_printf("[4G-TX] ch=%u len=%u\r\n", ch, len);
    if (!at_wait_prompt_owned(cmd, 3000U)) {
        dbg_printf("[4G-TX] fail stage=prompt ch=%u\r\n", ch);
        goto done;
    }
    if (!usart_send_buf(data, len)) {
        dbg_printf("[4G-TX] fail stage=payload ch=%u\r\n", ch);
        goto done;
    }
    if (!at_send_wait_owned("", "SEND OK", 5000U)) {
        /* The '>' prompt was granted and the payload went out, so the frame is
         * probably on the wire; only the confirmation is missing.  Echo what
         * the modem actually said -- a bare timeout gave no way to tell an
         * unresponsive module from a rejected send. */
        dbg_printf("[4G-TX] fail stage=result ch=%u resp=\"", ch);
        at_dump_response();
        dbg_printf("\"\r\n");
        s_tcp_send_ambiguous = true;
        goto done;
    }
    dbg_printf("[4G-TX] ch=%u SEND OK\r\n", ch);
    result = 0;
done:
    at_owner_release(AT_OWNER_TCP);
    return result;
}

int ec800m_udp_send_once(const char *ip, uint16_t port,
                         const uint8_t *data, uint16_t len)
{
    const uint8_t ch = EC800M_CH_OTA;
    char cmd[128];
    if (!ip || !ip[0] || !data || len == 0U || len > 512U ||
        !ec800m_is_ready() || s_tcp[ch].state != TCP_STATE_CLOSED)
        return -1;
    if (!at_owner_acquire(AT_OWNER_TCP)) return -2;
    (void)snprintf(cmd, sizeof(cmd), "AT+QIOPEN=1,%u,\"UDP\",\"%s\",%u,0,0",
                   (unsigned)ch, ip, (unsigned)port);
    s_tcp[ch].state = TCP_STATE_OPENING;
    if (!at_send_wait_owned(cmd, "OK", 5000U)) goto fail;
    if (s_tcp[ch].state != TCP_STATE_OPEN) {
        /* QIOPEN URC is consumed by the response pump; accept a successful
         * command as open for UDP and let QISEND report any failure. */
        s_tcp[ch].state = TCP_STATE_OPEN;
    }
    (void)snprintf(cmd, sizeof(cmd), "AT+QISEND=%u,%u", (unsigned)ch,
                   (unsigned)len);
    if (!at_wait_prompt_owned(cmd, 3000U) || !usart_send_buf(data, len) ||
        !at_send_wait_owned("", "SEND OK", 5000U)) goto fail_close;
    (void)snprintf(cmd, sizeof(cmd), "AT+QICLOSE=%u", (unsigned)ch);
    (void)at_send_wait_owned(cmd, "OK", 2000U);
    s_tcp[ch].state = TCP_STATE_CLOSED;
    at_owner_release(AT_OWNER_TCP);
    return 0;
fail_close:
    (void)snprintf(cmd, sizeof(cmd), "AT+QICLOSE=%u", (unsigned)ch);
    (void)at_send_wait_owned(cmd, "OK", 1000U);
fail:
    s_tcp[ch].state = TCP_STATE_CLOSED;
    at_owner_release(AT_OWNER_TCP);
    return -1;
}

int ec800m_udp_txn(const char *ip, uint16_t port,
                   const uint8_t *tx, uint16_t tx_len,
                   uint8_t *rx, uint16_t rx_cap, uint32_t timeout_ms)
{
    (void)timeout_ms;
    if (rx && rx_cap) rx[0] = 0U;
    return ec800m_udp_send_once(ip, port, tx, tx_len);
}

int ec800m_udp_txn_start(const char *ip, uint16_t port,
                         const uint8_t *tx, uint16_t tx_len,
                         uint8_t *rx, uint16_t rx_cap, uint32_t timeout_ms)
{
    if (s_udp_txn_state != UDP_TXN_IDLE && s_udp_txn_state != UDP_TXN_DONE) return -2;
    if (!ip || !tx || !tx_len || tx_len > 512U || !rx || !rx_cap) return -1;
    s_udp_ip = ip; s_udp_port = port; s_udp_data = tx; s_udp_len = tx_len;
    s_udp_rx = rx; s_udp_rx_cap = rx_cap; s_udp_timeout = (uint16_t)(timeout_ms > 60000U ? 60000U : timeout_ms);
    s_udp_result = -1; s_udp_txn_state = UDP_TXN_OPEN_CMD; return 0;
}

void ec800m_udp_txn_process(void)
{
    if (s_udp_txn_state == UDP_TXN_OPEN_CMD) { s_udp_txn_state = UDP_TXN_SEND_CMD; return; }
    if (s_udp_txn_state == UDP_TXN_SEND_CMD) {
        s_udp_result = ec800m_udp_txn(s_udp_ip, s_udp_port, s_udp_data, s_udp_len,
                                      s_udp_rx, s_udp_rx_cap, s_udp_timeout);
        s_udp_txn_state = UDP_TXN_CLOSE_CMD;
        return;
    }
    if (s_udp_txn_state == UDP_TXN_CLOSE_CMD) s_udp_txn_state = UDP_TXN_DONE;
}

int ec800m_udp_txn_result(void)
{
    if (s_udp_txn_state != UDP_TXN_DONE) return -2;
    s_udp_txn_state = UDP_TXN_IDLE; return s_udp_result;
}

void ec800m_tcp_close(uint8_t ch)
{
    if (ch >= EC800M_CH_MAX) return;
    char cmd[32];
    snprintf(cmd, sizeof(cmd), "AT+QICLOSE=%d", ch);
    at_send_wait(cmd, "OK", 3000);
    s_tcp[ch].state = TCP_STATE_CLOSED;
}

tcp_state_t ec800m_tcp_state(uint8_t ch)
{
    if (ch >= EC800M_CH_MAX) return TCP_STATE_CLOSED;
    return s_tcp[ch].state;
}

static void copy_identity(char *buf, uint8_t size, const char *identity)
{
    if (buf == NULL || size == 0U) return;
    (void)strncpy(buf, identity, (size_t)size - 1U);
    buf[size - 1U] = '\0';
}

void ec800m_get_imei(char *buf, uint8_t size) { copy_identity(buf, size, s_imei); }
void ec800m_get_iccid(char *buf, uint8_t size){ copy_identity(buf, size, s_iccid); }
int  ec800m_get_csq(void) { return s_csq; }

#define EC800M_NTP_SERVER "ntp.aliyun.com"

bool ec800m_ntp_sync(ec800m_time_t *out)
{
    unsigned year = 0U, month = 0U, day = 0U, hour = 0U, minute = 0U, second = 0U;
    int tz_quarter = 0;
    uint16_t y; uint8_t mo, d, h, mi;

    if (out == NULL) return false;
    memset(out, 0, sizeof(*out));
    if (!ec800m_is_ready() || !at_owner_acquire(AT_OWNER_BLOCKING)) return false;

    bool ok = at_send_wait_owned("AT+QNTP=1,\"" EC800M_NTP_SERVER "\",123,0",
                                 "+QNTP:", 10000);
    if (ok) {
        const char *p = strstr(s_at_resp, "+QNTP:");
        ok = p != NULL &&
             parse_qntp(p, &year, &month, &day, &hour, &minute, &second,
                        &tz_quarter);
    }
    at_owner_release(AT_OWNER_BLOCKING);
    process_deferred_urc_one();
    if (!ok) return false;

    y = (uint16_t)year; mo = (uint8_t)month; d = (uint8_t)day;
    h = (uint8_t)hour; mi = (uint8_t)minute;
    /* Quoted timestamp is local time (already shifted by tz_quarter east of
     * UTC); subtract that offset to recover UTC. */
    ntp_shift_minutes(&y, &mo, &d, &h, &mi, -tz_quarter * 15);
    out->year = y; out->month = mo; out->day = d;
    out->hour = h; out->minute = mi; out->second = (uint8_t)second;
    out->valid = true;
    return true;
}

void ec800m_sleep_enable(void)
{
    at_send_wait("AT+QSCLK=1", "OK", 1000);
    GPIO_SetBits(EC800M_DTR_PORT, EC800M_DTR_PIN);
}

void ec800m_sleep_disable(void)
{
    GPIO_ResetBits(EC800M_DTR_PORT, EC800M_DTR_PIN);
    delay_ms(50);
    at_send_wait("AT+QSCLK=0", "OK", 1000);
}

void ec800m_register_recv(ec800m_recv_cb_t cb) { s_recv_cb = cb; }
void ec800m_register_ota_recv(ec800m_recv_cb_t cb) { s_ota_recv_cb = cb; }
void ec800m_register_agnss_recv(ec800m_recv_cb_t cb) { s_agnss_recv_cb = cb; }

/* Legacy no-op kept for API compatibility (RX now uses USART3 interrupt). */
void ec800m_dma_rx_complete(void) { }
