"""Host contract for EC800M URC demultiplexing during owned AT waits."""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[2]


HEADERS = {
    "n32l40x.h": r'''
#ifndef N32L40X_H
#define N32L40X_H
#include <stdint.h>
typedef struct { uint32_t DAT; } usart_module_t;
typedef struct { uint32_t DUMMY; } dma_t;
typedef void GPIO_Module;
#define UART5 (&host_uart5)
#define EC800M_UART UART5
#define DMA_CH5 ((dma_t *)5)
#define DMA ((dma_t *)0)
#define DMA_FLAG_HT5 0x01U
#define DMA_FLAG_TC5 0x02U
#define USART_FLAG_TXDE 0x01U
#define USART_FLAG_TXC 0x02U
#define USART_FLAG_RXDNE 0x04U
#define USART_INT_RXDNE 0x08U
#define USART_FLAG_OREF 0x10U
#define RESET 0
#define SET 1
#define ENABLE 1
#define DISABLE 0
#define GPIOA ((GPIO_Module *)0x10)
#define GPIOB ((GPIO_Module *)0x11)
#define GPIO_PIN_7 7U
#define GPIO_PIN_8 8U
#define GPIO_PIN_15 15U
#define RCC_APB2_PERIPH_UART5 0U
extern usart_module_t host_uart5;
typedef int FlagStatus;
typedef int INTStatus;
uint32_t DMA_GetCurrDataCounter(dma_t *d);
FlagStatus DMA_GetFlagStatus(uint32_t flag, dma_t *d);
void DMA_ClearFlag(uint32_t flag, dma_t *d);
FlagStatus USART_GetFlagStatus(usart_module_t *u, uint16_t flag);
void USART_SendData(usart_module_t *u, uint16_t data);
uint16_t USART_ReceiveData(usart_module_t *u);
INTStatus USART_GetIntStatus(usart_module_t *u, uint16_t flag);
void IWDG_ReloadKey(void);
void GPIO_SetBits(GPIO_Module *p, uint16_t pin);
void GPIO_ResetBits(GPIO_Module *p, uint16_t pin);
int GPIO_ReadInputDataBit(GPIO_Module *p, uint16_t pin);
void delay_ms(uint32_t ms);
void delay_us(uint32_t us);
#endif
''',
    "config.h": r'''
#ifndef CONFIG_H
#define CONFIG_H
#include "n32l40x.h"
extern volatile uint32_t g_tick_ms;
#define TICK_MS() (g_tick_ms)
#define EC800M_RX_BUF_SIZE 1024U
#define EC800M_POWER_EN_PORT GPIOA
#define EC800M_POWER_EN_PIN GPIO_PIN_15
#define EC800M_PWRKEY_PORT GPIOA
#define EC800M_PWRKEY_PIN GPIO_PIN_8
#define EC800M_DTR_PORT GPIOB
#define EC800M_DTR_PIN GPIO_PIN_7
#endif
''',
    "hw_init.h": r'''
#ifndef HW_INIT_H
#define HW_INIT_H
#include "n32l40x.h"
#endif
''',
    "debug_uart.h": r'''
#ifndef DEBUG_UART_H
#define DEBUG_UART_H
int dbg_printf(const char *fmt, ...);
void dbg_putchar(char c);
#endif
''',
    "peripherals.h": r'''
#ifndef PERIPHERALS_H
#define PERIPHERALS_H
#include <stdbool.h>
void sms_process_urc(const char *line);
void sms_send_complete(bool success);
#endif
''',
}


HARNESS = r'''
#include <assert.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "n32l40x.h"
#include "config.h"
#include "ec800m.h"
#include "ec800m_at_response.h"
#include "flash_config.h"
#include "sms_ingress.h"

volatile uint32_t g_tick_ms;
static device_config_t config;
device_config_t *cfg_get(void) { return &config; }
usart_module_t host_uart5;
static uint16_t wr;
static unsigned injection;
static unsigned fragment_body_mode;
static unsigned binary_result_mode;
static unsigned ota_echo_mode;
static char ota_test_key[21];
static unsigned qird_phase;
static char tx_log[1024];
static unsigned tx_len;
static char sms_from[32];
static char sms_body[192];
static unsigned sms_calls;
static uint8_t tcp_payload[8];
static uint16_t tcp_payload_len;
static char diag_log[1024];
static unsigned diag_len;

extern uint8_t EC800M_RX_BUF[EC800M_RX_BUF_SIZE];
void ec800m_test_set_state(ec800m_state_t state);
void ec800m_test_set_imei(const char *imei);
void ec800m_test_set_tcp_open(uint8_t ch);
bool ec800m_test_parse_iccid(const char *response, char out[22]);
bool ec800m_test_iccid_retry_should_advance(bool parsed, uint8_t *attempts);
bool ec800m_test_iccid_refresh_required(bool sim_identity_ready,
                                        const char *iccid);
void ec800m_get_imei(char *buf, uint8_t size);

static void host_feed_rx(const char *text)
{
    size_t n = strlen(text);
    for (size_t i = 0U; i < n; ++i) {
        EC800M_RX_BUF[wr++] = (uint8_t)text[i];
        if (wr == EC800M_RX_BUF_SIZE) wr = 0U;
    }
}

static void host_feed_bytes(const uint8_t *data, size_t length)
{
    for (size_t i = 0U; i < length; ++i) {
        EC800M_RX_BUF[wr++] = data[i];
        if (wr == EC800M_RX_BUF_SIZE) wr = 0U;
    }
}

void host_uart_tx(uint8_t byte)
{
    if (tx_len + 1U < sizeof tx_log) {
        tx_log[tx_len++] = (char)byte;
        tx_log[tx_len] = '\0';
    }
    if (ota_echo_mode == 1U && byte == '\n' && strstr(tx_log, "AT+QISEND=1,3\r\n") != NULL) {
        host_feed_rx(">\r\n");ota_echo_mode=2U;
    } else if (ota_echo_mode == 2U && byte == 'c') {
        host_feed_rx("\r\nX-Device-Key: ");host_feed_rx(ota_test_key);host_feed_rx("\r\nERROR\r\n");ota_echo_mode=3U;
    } else if (fragment_body_mode == 1U && byte == '\n' && strstr(tx_log, "AT+QISEND=0,3\r\n") != NULL) {
        host_feed_rx(">\r\n");
        fragment_body_mode = 2U;
    } else if (binary_result_mode == 1U && byte == '\n' && strstr(tx_log, "AT+QISEND=0,3\r\n") != NULL) {
        host_feed_rx(">\r\n");
        binary_result_mode = 2U;
    } else if (injection == 0U && byte == '\n' && strstr(tx_log, "AT+QISEND=0,3\r\n") != NULL) {
        host_feed_rx(">\r\n+CMT: \"13900000004\",\"\",\"\"\r\nPARAM#\r\n+QIURC: \"closed\",0\r\n");
        injection = 1U;
    } else if (fragment_body_mode == 2U && byte == 'c') {
        /* This body is deliberately unterminated: it must never satisfy the
         * subsequent TCP SEND OK expectation while the AT owner is held. */
        host_feed_rx("\r\n+CMT: \"13900000005\",\"\",\"\"\r\nSEND OK");
        fragment_body_mode = 3U;
    } else if (binary_result_mode == 2U && byte == 'c') {
        static const uint8_t result[] = {
            ' ', 0x7eU, 0x00U, 0x02U, '\r', '\n',
            'S', 'E', 'N', 'D', ' ', 'O', 'K', '\r', '\n'
        };
        host_feed_bytes(result, sizeof result);
        binary_result_mode = 3U;
    } else if (injection == 1U && byte == 'c') {
        host_feed_rx("\r\nSEND OK\r\n");
        injection = 2U;
    } else if (qird_phase == 1U && byte == '\n' && strstr(tx_log, "AT+QIRD=0,1200\r\n") != NULL) {
        /* With command echo disabled, the response buffer may begin at the
         * QIRD result line rather than with a leading blank line. */
        host_feed_rx("+QIRD: 5\r\n");
        qird_phase = 2U;
    } else if (qird_phase == 4U && byte == '\n' && strstr(tx_log, "AT+QIRD=0,1200\r\n") != NULL) {
        host_feed_rx("+QIRD: X\r\n\r\nOK\r\n");
        qird_phase = 5U;
    }
}

uint32_t DMA_GetCurrDataCounter(dma_t *d)
{
    (void)d;
    return (uint32_t)(EC800M_RX_BUF_SIZE - wr);
}
FlagStatus DMA_GetFlagStatus(uint32_t flag, dma_t *d)
{
    (void)flag; (void)d; return RESET;
}
void DMA_ClearFlag(uint32_t flag, dma_t *d) { (void)flag; (void)d; }
FlagStatus USART_GetFlagStatus(usart_module_t *u, uint16_t flag)
{
    (void)u;
    return (flag == USART_FLAG_TXDE || flag == USART_FLAG_TXC) ? SET : RESET;
}
void USART_SendData(usart_module_t *u, uint16_t data) { (void)u; host_uart_tx((uint8_t)data); }
uint16_t USART_ReceiveData(usart_module_t *u) { (void)u; return 0U; }
INTStatus USART_GetIntStatus(usart_module_t *u, uint16_t flag) { (void)u; (void)flag; return RESET; }
void IWDG_ReloadKey(void)
{
    ++g_tick_ms;
    if (qird_phase == 2U) {
        static const uint8_t tail[] = { 0x7e, 0x00, 0x0d, 0x0a, 0x7e, '\r', '\n', '\r', '\n', 'O', 'K', '\r', '\n' };
        host_feed_bytes(tail, sizeof tail);
        qird_phase = 3U;
    }
}
void GPIO_SetBits(GPIO_Module *p, uint16_t pin) { (void)p; (void)pin; }
void GPIO_ResetBits(GPIO_Module *p, uint16_t pin) { (void)p; (void)pin; }
int GPIO_ReadInputDataBit(GPIO_Module *p, uint16_t pin) { (void)p; (void)pin; return SET; }
void delay_ms(uint32_t ms) { g_tick_ms += ms; }
void delay_us(uint32_t us) { (void)us; }
int dbg_printf(const char *fmt, ...)
{
    int written;
    va_list args;
    va_start(args, fmt);
    written = vsnprintf(diag_log + diag_len, sizeof diag_log - diag_len, fmt, args);
    va_end(args);
    if (written > 0 && (unsigned)written < sizeof diag_log - diag_len)
        diag_len += (unsigned)written;
    return written;
}
void dbg_putchar(char c) { (void)c; }
void sms_send_complete(bool success) { (void)success; }
void sms_process_urc(const char *line) { sms_ingress_feed_line(line); }

static void sms_cb(const char *from, const uint8_t *cmd, uint16_t len)
{
    assert(len < sizeof sms_body);
    strncpy(sms_from, from, sizeof sms_from - 1U);
    sms_from[sizeof sms_from - 1U] = '\0';
    memcpy(sms_body, cmd, len);
    sms_body[len] = '\0';
    ++sms_calls;
}

static void tcp_cb(uint8_t ch, const uint8_t *data, uint16_t len)
{
    assert(ch == 0U && len <= sizeof tcp_payload);
    memcpy(tcp_payload, data, len);
    tcp_payload_len = len;
}

int main(void)
{
    {
        static const char payload_token[] = {
            (char)0x7e, 0x00, 0x02, 'S', 'E', 'N', 'D', ' ', 'O', 'K',
            (char)0x7e
        };
        static const char modem_result[] = {
            (char)0x7e, 0x00, '\r', '\n',
            'S', 'E', 'N', 'D', ' ', 'O', 'K', '\r', '\n'
        };
        assert(!ec800m_at_response_has_line(
            payload_token, sizeof payload_token, "SEND OK"));
        assert(ec800m_at_response_has_line(
            modem_result, sizeof modem_result, "SEND OK"));
    }
    {
        char iccid[22] = "unchanged";
        assert(ec800m_test_parse_iccid("\r\n+QCCID: 8986001234567890123\r\nOK\r\n", iccid));
        assert(strcmp(iccid, "8986001234567890123") == 0);
        assert(ec800m_test_parse_iccid("+QCCID:\t89860012345678901234\r\nOK\r\n", iccid));
        assert(strcmp(iccid, "89860012345678901234") == 0);
        assert(ec800m_test_parse_iccid("\r\n+QCCID: 898604A1192490075609\r\nOK\r\n", iccid));
        assert(strcmp(iccid, "898604A1192490075609") == 0);
        assert(ec800m_test_parse_iccid("+QCCID: 898604a1192490075609\r\nOK\r\n", iccid));
        assert(strcmp(iccid, "898604A1192490075609") == 0);
        assert(!ec800m_test_parse_iccid("+QCCID: 898604121025", iccid));
        assert(strcmp(iccid, "898604A1192490075609") == 0);
        assert(!ec800m_test_parse_iccid("+QCCID: 898600123456789012345", iccid));
        assert(!ec800m_test_parse_iccid("+QCCID: 89860012345G7890123", iccid));
    }
    {
        uint8_t attempts = 0U;
        assert(!ec800m_test_iccid_retry_should_advance(false, &attempts));
        assert(attempts == 1U);
        assert(!ec800m_test_iccid_retry_should_advance(false, &attempts));
        assert(attempts == 2U);
        assert(ec800m_test_iccid_retry_should_advance(false, &attempts));
        assert(attempts == 3U);
        assert(ec800m_test_iccid_retry_should_advance(true, &attempts));
        assert(attempts == 0U);
    }
    assert(!ec800m_test_iccid_refresh_required(false, ""));
    assert(ec800m_test_iccid_refresh_required(true, ""));
    assert(ec800m_test_iccid_refresh_required(true, "898600123456"));
    assert(!ec800m_test_iccid_refresh_required(
        true, "898604A1192490075609"));
    assert(!ec800m_test_iccid_refresh_required(
        true, "89860012345678901234"));
    {
        char shortened[4] = { 'X', 'X', 'X', 'X' };
        ec800m_test_set_imei("123456789012345");
        ec800m_get_imei(shortened, sizeof shortened);
        assert(memcmp(shortened, "123\0", sizeof shortened) == 0);
        ec800m_get_imei(NULL, 0U);
    }
    ec800m_test_set_state(EC800M_STATE_READY);
    ec800m_test_set_tcp_open(0U);
    sms_ingress_set_callback(sms_cb);
    assert(ec800m_tcp_send(0U, (const uint8_t *)"abc", 3U) == 0);

    /* +CMT survives the TCP owner and is available through the real FIFO. */
    sms_ingress_process();
    assert(sms_calls == 1U);
    assert(strcmp(sms_from, "13900000004") == 0);
    assert(strcmp(sms_body, "PARAM") == 0);

    /* QIURC work was deferred while TCP owned the AT channel. */
    assert(ec800m_tcp_state(0U) == TCP_STATE_OPEN);
    ec800m_process();
    assert(ec800m_tcp_state(0U) == TCP_STATE_CLOSED);

    /* QIRD must remain owned until its final OK and preserve binary payload. */
    ec800m_test_set_tcp_open(0U);
    ec800m_register_recv(tcp_cb);
    qird_phase = 1U;
    host_feed_rx("\r\n+QIURC: \"recv\",0\r\n");
    ec800m_process();
    assert(tcp_payload_len == 5U);
    assert(tcp_payload[0] == 0x7eU && tcp_payload[1] == 0x00U);
    assert(tcp_payload[2] == 0x0dU && tcp_payload[3] == 0x0aU && tcp_payload[4] == 0x7eU);
    assert(strstr(diag_log, "[4G-RX] ch=0 event=recv") != NULL);
    assert(strstr(diag_log, "[4G-RX] ch=0 qird=5") != NULL);
    assert(strstr(diag_log, "PARAM") == NULL);

    /* Malformed framing reports structure only, never response bytes. */
    tcp_payload_len = 0U;
    qird_phase = 4U;
    host_feed_rx("\r\n+QIURC: \"recv\",0\r\n");
    ec800m_process();
    assert(strstr(diag_log, "qird_fail=FORMAT stage=") != NULL);
    assert(strstr(diag_log, " total=") != NULL);
    assert(strstr(diag_log, " hdr=") != NULL);
    assert(strstr(diag_log, " decl=") != NULL);
    assert(strstr(diag_log, " remain=") != NULL);
    assert(strstr(diag_log, " tail=") != NULL);

    /* scanf-style partial matches must not turn malformed URCs into events. */
    ec800m_test_set_tcp_open(0U);
    host_feed_rx("\r\n+QIURC: \"closed\",0junk\r\n");
    ec800m_process();
    assert(ec800m_tcp_state(0U) == TCP_STATE_OPEN);

    /* An unterminated +CMT body containing SEND OK cannot complete a TCP
     * wait before its line boundary arrives. */
    ec800m_test_set_tcp_open(0U);
    fragment_body_mode = 1U;
    assert(ec800m_tcp_send(0U, (const uint8_t *)"abc", 3U) != 0);

    /* A platform response can arrive before the modem's SEND OK. Binary
     * bytes, including NUL, must not truncate the bounded result matcher. */
    ec800m_test_set_tcp_open(0U);
    fragment_body_mode = 0U;
    binary_result_mode = 1U;
    assert(ec800m_tcp_send(0U, (const uint8_t *)"abc", 3U) == 0);

    /* Modem failure may echo payload into the AT response: OTA logs must not. */
    ec800m_test_set_tcp_open(1U);ota_echo_mode=1U;
    memset(ota_test_key,'Q',20);ota_test_key[20]=0;
    tx_len=diag_len=0;tx_log[0]=diag_log[0]=0;
    assert(ec800m_tcp_send(1U,(const uint8_t *)"abc",3U)!=0);
    assert(ota_echo_mode==3U);
    assert(strstr(diag_log,"fail stage=result ch=1")!=NULL);
    assert(strstr(diag_log,ota_test_key)==NULL);

    puts("test_ec800m_urc_demux: PASS");
    return 0;
}
'''


def compiler() -> str | None:
    return os.environ.get("CC") or shutil.which("gcc") or shutil.which("cc")


def main() -> None:
    cc = compiler()
    if not cc:
        if os.environ.get("REQUIRE_GCC") == "1":
            raise AssertionError("REQUIRE_GCC=1 but no gcc/cc found")
        print("test_ec800m_urc_demux: SKIP (gcc/cc unavailable)")
        return
    with tempfile.TemporaryDirectory() as td:
        directory = pathlib.Path(td)
        for name, content in HEADERS.items():
            (directory / name).write_text(content, encoding="ascii")
        harness = directory / "harness.c"
        output = directory / "harness.exe"
        harness.write_text(HARNESS, encoding="ascii")
        command = [
            cc,
            "-std=c99",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-Wno-dangling-else",
            "-ffunction-sections",
            "-fdata-sections",
            "-DEC800M_HOST_TEST",
            "-I",
            str(directory),
            "-I",
            str(ROOT / "include"),
            str(harness),
            str(ROOT / "src" / "ec800m.c"),
            str(ROOT / "src" / "ec800m_at_response.c"),
            str(ROOT / "src" / "sms_ingress.c"),
            str(ROOT / "src" / "sms_command.c"),
            "-Wl,--gc-sections",
            "-o",
            str(output),
        ]
        build = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        if build.returncode:
            raise AssertionError("C harness compile failed:\n" + build.stderr)
        run = subprocess.run([str(output)], cwd=ROOT, capture_output=True, text=True)
        if run.returncode:
            raise AssertionError(
                "C harness failed (exit %d):\n%s\n%s"
                % (run.returncode, run.stdout, run.stderr)
            )
        print(run.stdout.strip())


if __name__ == "__main__":
    main()
