#include "ec800m.h"
#include "config.h"
#include "hw_init.h"
#include "debug_uart.h"
#include "n32l40x.h"
#include <string.h>
#include <stdio.h>
#include <stdlib.h>

/* ── RX ring buffer (filled by USART3 RX interrupt) ──────────────────────── */
static uint8_t           s_rx_buf[EC800M_RX_BUF_SIZE];
static volatile uint16_t s_rx_wr = 0;   /* write index, advanced in ISR     */
static uint16_t          s_rx_rd = 0;   /* read index, advanced in main loop */

/* Set to 1 to echo every raw byte from the modem to the debug UART.
 * Invaluable for bring-up; set to 0 once the link is confirmed working. */
#define EC800M_RX_ECHO  1

/* Line accumulation for AT response parsing */
#define AT_LINE_MAX  256
static char    s_line_buf[AT_LINE_MAX];
static uint16_t s_line_len = 0;

/* AT command send/wait */
#define AT_RESP_MAX  512
static char    s_at_resp[AT_RESP_MAX];
static volatile bool s_at_done = false;

/* Module info */
static char s_imei[16]  = {0};
static char s_iccid[22] = {0};
static int  s_csq       = 0;

/* State */
static ec800m_state_t s_state      = EC800M_STATE_OFF;
static uint32_t       s_state_enter_ms = 0;
static uint32_t       s_init_step   = 0;

/* TCP channels */
static tcp_channel_t s_tcp[EC800M_CH_MAX];

/* Upper-layer receive callback */
static ec800m_recv_cb_t s_recv_cb = NULL;

/* ── RX init: enable USART3 RXNE interrupt (same proven path as GPS/debug) ── */
static void rx_irq_init(void)
{
    s_rx_wr = 0;
    s_rx_rd = 0;

    /* Disable USART3 DMA RX request (was enabled in hw_usart_init) and use IRQ */
    USART_EnableDMA(EC800M_UART, USART_DMAREQ_RX, DISABLE);
    USART_ConfigInt(EC800M_UART, USART_INT_RXDNE, ENABLE);

    NVIC_InitType n;
    n.NVIC_IRQChannel                   = USART3_IRQn;
    n.NVIC_IRQChannelPreemptionPriority = 1;
    n.NVIC_IRQChannelSubPriority        = 0;
    n.NVIC_IRQChannelCmd                = ENABLE;
    NVIC_Init(&n);
}

/* USART3 RX interrupt — store each byte into the ring buffer */
void UART5_IRQHandler(void)
{
    if (USART_GetIntStatus(EC800M_UART, USART_INT_RXDNE)) {
        uint8_t b = (uint8_t)USART_ReceiveData(EC800M_UART);
        uint16_t next = (uint16_t)((s_rx_wr + 1) % EC800M_RX_BUF_SIZE);
        if (next != s_rx_rd) {        /* drop byte if buffer full */
            s_rx_buf[s_rx_wr] = b;
            s_rx_wr = next;
        }
    }
    /* Clear overrun if it occurred (reading STS then DAT clears ORE) */
    if (USART_GetFlagStatus(EC800M_UART, USART_FLAG_OREF) != RESET) {
        (void)USART_ReceiveData(EC800M_UART);
    }
}

/* ── Low-level send ───────────────────────────────────────────────────────── */
static void usart_send_str(const char *s)
{
    while (*s) {
        while (USART_GetFlagStatus(EC800M_UART, USART_FLAG_TXDE) == RESET);
        USART_SendData(EC800M_UART, (uint8_t)*s++);
    }
}

static void usart_send_buf(const uint8_t *buf, uint16_t len)
{
    for (uint16_t i = 0; i < len; i++) {
        while (USART_GetFlagStatus(EC800M_UART, USART_FLAG_TXDE) == RESET);
        USART_SendData(EC800M_UART, buf[i]);
    }
}

/* ── Send AT command and wait for response (blocking, timeout ms) ─────────── */
static bool at_send_wait(const char *cmd, const char *expect,
                          uint32_t timeout_ms)
{
    memset(s_at_resp, 0, sizeof(s_at_resp));

#if EC800M_RX_ECHO
    if (cmd[0]) dbg_printf(">> %s\r\n", cmd);
#endif
    usart_send_str(cmd);
    usart_send_str("\r\n");

    uint32_t start = TICK_MS();
    uint16_t resp_pos = 0;

    while ((TICK_MS() - start) < timeout_ms) {
        /* Keep the watchdog fed during long blocking AT waits */
        IWDG_ReloadKey();
        /* drain new bytes from the interrupt-filled ring buffer */
        while (s_rx_rd != s_rx_wr) {
            uint8_t c = s_rx_buf[s_rx_rd];
            s_rx_rd = (uint16_t)((s_rx_rd + 1) % EC800M_RX_BUF_SIZE);
#if EC800M_RX_ECHO
            dbg_putchar((char)c);   /* echo raw modem byte to debug UART */
#endif
            if (resp_pos < AT_RESP_MAX - 1)
                s_at_resp[resp_pos++] = (char)c;
        }
        s_at_resp[resp_pos] = '\0';
        if (expect[0] && strstr(s_at_resp, expect)) return true;
        if (strstr(s_at_resp, "ERROR")) return false;
    }
    return false;
}

/* ── Power control ────────────────────────────────────────────────────────── */
void ec800m_power_on(void)
{
    GPIO_SetBits(EC800M_PWRKEY_PORT, EC800M_PWRKEY_PIN);
    delay_ms(600);
    GPIO_ResetBits(EC800M_PWRKEY_PORT, EC800M_PWRKEY_PIN);
    delay_ms(2000);
    dbg_printf("[4G] power on\r\n");
}

void ec800m_power_off(void)
{
    at_send_wait("AT+QPOWD=0", "POWERED DOWN", 5000);
    GPIO_ResetBits(EC800M_PWRKEY_PORT, EC800M_PWRKEY_PIN);
    s_state = EC800M_STATE_OFF;
}

void ec800m_reset(void)
{
    ec800m_power_off();
    delay_ms(1000);
    ec800m_power_on();
    s_state = EC800M_STATE_BOOTING;
    s_state_enter_ms = TICK_MS();
    s_init_step = 0;
}

/* ── Init sequence steps ──────────────────────────────────────────────────── */
static const char *s_init_cmds[] = {
    "ATE0",
    "AT+QURCCFG=\"urcport\",\"uart1\"",
    "AT+CMGF=1",
    "AT+CNMI=2,1,0,0,0",
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
            if (TICK_MS() - s_state_enter_ms > 15000) {
                dbg_printf("[4G] no AT response, reset\r\n");
                ec800m_reset();
            }
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
            char *p = strstr(s_at_resp, "\n");
            if (p) {
                p++;
                uint8_t i = 0;
                while (*p >= '0' && *p <= '9' && i < 15) s_imei[i++] = *p++;
                s_imei[i] = '\0';
            }
        }
        s_init_step++;
        break;
    case 7: /* ICCID */
        if (at_send_wait("AT+QCCID", "OK", 2000)) {
            char *p = strstr(s_at_resp, "+QCCID: ");
            if (p) {
                p += 8;
                uint8_t i = 0;
                while (*p >= '0' && *p <= '9' && i < 20) s_iccid[i++] = *p++;
                s_iccid[i] = '\0';
            }
        }
        s_init_step++;
        break;
    case 8:
        s_state = EC800M_STATE_SIM_CHECK;
        s_state_enter_ms = TICK_MS();
        dbg_printf("[4G] init done, IMEI=%s\r\n", s_imei);
        break;
    }
}

static void state_machine_sim(void)
{
    if (at_send_wait("AT+CIMI", "OK", 2000)) {
        s_state = EC800M_STATE_NETWORK_REG;
        s_state_enter_ms = TICK_MS();
    } else if (TICK_MS() - s_state_enter_ms > 30000) {
        dbg_printf("[4G] no SIM card\r\n");
        s_state = EC800M_STATE_ERROR;
    }
}

static void state_machine_netreg(void)
{
    /* Try LTE first, fall back to 2G/3G */
    bool reg = false;
    if (at_send_wait("AT+CEREG?", "+CEREG: 0,1", 2000) ||
        at_send_wait("AT+CEREG?", "+CEREG: 0,5", 500)) {
        reg = true;
    } else if (at_send_wait("AT+CGREG?", "+CGREG: 0,1", 2000) ||
               at_send_wait("AT+CGREG?", "+CGREG: 0,5", 500)) {
        reg = true;
    }

    if (reg) {
        s_state = EC800M_STATE_PDP_ACTIVE;
        s_state_enter_ms = TICK_MS();
        dbg_printf("[4G] network registered\r\n");
    } else if (TICK_MS() - s_state_enter_ms > 60000) {
        dbg_printf("[4G] network reg timeout, reset\r\n");
        ec800m_reset();
    }
}

static void state_machine_pdp(void)
{
    /* activate PDP context 1 */
    at_send_wait("AT+QIACT=1", "OK", 10000);
    if (at_send_wait("AT+QIACT?", "+QIACT:", 3000)) {
        s_state = EC800M_STATE_READY;
        s_state_enter_ms = TICK_MS();
        dbg_printf("[4G] PDP active, ready\r\n");
    } else if (TICK_MS() - s_state_enter_ms > 30000) {
        dbg_printf("[4G] PDP fail\r\n");
        s_state = EC800M_STATE_NETWORK_REG;
        s_state_enter_ms = TICK_MS();
    }
}

/* ── URC / receive processing ─────────────────────────────────────────────── */
static void process_urc(const char *line)
{
    int ch;
    /* +QIOPEN: ch,0  → open success */
    if (sscanf(line, "+QIOPEN: %d,0", &ch) == 1 && ch < EC800M_CH_MAX) {
        s_tcp[ch].state = TCP_STATE_OPEN;
        dbg_printf("[4G] TCP ch%d open\r\n", ch);
        return;
    }
    /* +QIURC: "recv",ch */
    if (sscanf(line, "+QIURC: \"recv\",%d", &ch) == 1 && ch < EC800M_CH_MAX) {
        char cmd[32];
        snprintf(cmd, sizeof(cmd), "AT+QIRD=%d,1200", ch);
        if (at_send_wait(cmd, "+QIRD:", 2000) && s_recv_cb) {
            char *p = strstr(s_at_resp, "+QIRD: ");
            if (p) {
                uint16_t dlen = (uint16_t)atoi(p + 7);
                p = strstr(p, "\r\n");
                if (p && dlen > 0)
                    s_recv_cb((uint8_t)ch, (uint8_t *)(p + 2), dlen);
            }
        }
        return;
    }
    /* +QIURC: "closed",ch */
    if (sscanf(line, "+QIURC: \"closed\",%d", &ch) == 1 && ch < EC800M_CH_MAX) {
        s_tcp[ch].state = TCP_STATE_CLOSED;
        dbg_printf("[4G] TCP ch%d closed\r\n", ch);
        return;
    }
    /* +QIURC: "pdpdeact",1 */
    if (strstr(line, "+QIURC: \"pdpdeact\"")) {
        dbg_printf("[4G] PDP deact, re-register\r\n");
        s_state = EC800M_STATE_NETWORK_REG;
        s_state_enter_ms = TICK_MS();
        for (int i = 0; i < EC800M_CH_MAX; i++)
            s_tcp[i].state = TCP_STATE_CLOSED;
    }
    /* +CSQ */
    if (sscanf(line, "+CSQ: %d,", &s_csq) == 1) return;
}

/* ── Drain RX ring and process complete lines (URCs) ─────────────────────── */
static void drain_rx(void)
{
    while (s_rx_rd != s_rx_wr) {
        char c = (char)s_rx_buf[s_rx_rd];
        s_rx_rd = (uint16_t)((s_rx_rd + 1) % EC800M_RX_BUF_SIZE);

#if EC800M_RX_ECHO
        dbg_putchar(c);
#endif
        if (c == '\r') continue;
        if (c == '\n') {
            s_line_buf[s_line_len] = '\0';
            if (s_line_len > 0) process_urc(s_line_buf);
            s_line_len = 0;
        } else {
            if (s_line_len < AT_LINE_MAX - 1)
                s_line_buf[s_line_len++] = c;
        }
    }
}

/* ── Public API ───────────────────────────────────────────────────────────── */
void ec800m_init(void)
{
    rx_irq_init();
    memset(s_tcp, 0, sizeof(s_tcp));
    s_state = EC800M_STATE_BOOTING;
    s_state_enter_ms = TICK_MS();
    s_init_step = 0;
    ec800m_power_on();
}

void ec800m_process(void)
{
    drain_rx();

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
        /* Periodic CSQ poll every 30 s */
        if ((TICK_MS() % 30000) < 100)
            at_send_wait("AT+CSQ", "OK", 1000);
        break;
    case EC800M_STATE_ERROR:
        if (TICK_MS() - s_state_enter_ms > 60000) ec800m_reset();
        break;
    default: break;
    }
}

ec800m_state_t ec800m_get_state(void) { return s_state; }
bool ec800m_is_ready(void)            { return s_state == EC800M_STATE_READY; }

int ec800m_tcp_open(uint8_t ch, const char *ip, uint16_t port)
{
    if (ch >= EC800M_CH_MAX || !ec800m_is_ready()) return -1;
    if (s_tcp[ch].state == TCP_STATE_OPEN) return 0;

    char cmd[128];
    snprintf(cmd, sizeof(cmd),
             "AT+QIOPEN=1,%d,\"TCP\",\"%s\",%u,0,1", ch, ip, port);
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

int ec800m_tcp_send(uint8_t ch, const uint8_t *data, uint16_t len)
{
    if (ch >= EC800M_CH_MAX || s_tcp[ch].state != TCP_STATE_OPEN) return -1;

    char cmd[32];
    snprintf(cmd, sizeof(cmd), "AT+QISEND=%d,%u", ch, len);
    if (!at_send_wait(cmd, ">", 3000)) return -1;
    usart_send_buf(data, len);
    return at_send_wait("", "SEND OK", 5000) ? 0 : -1;
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

void ec800m_get_imei(char *buf, uint8_t size) { strncpy(buf, s_imei,  size-1); }
void ec800m_get_iccid(char *buf, uint8_t size){ strncpy(buf, s_iccid, size-1); }
int  ec800m_get_csq(void) { return s_csq; }

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

/* Legacy no-op kept for API compatibility (RX now uses USART3 interrupt). */
void ec800m_dma_rx_complete(void) { }
