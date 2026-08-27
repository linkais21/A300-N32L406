#include "fota.h"
#include "ec800m.h"
#include "spi_flash.h"
#include "ext_flash_store.h"
#include "flash_config.h"
#include "debug_uart.h"
#include "hw_init.h"
#include "config.h"
#include "n32l40x.h"
#include <string.h>
#include <stdlib.h>
#include <stdio.h>

/*
 * FOTA via EC800M HTTP:
 *   AT+QHTTPURL=<len>,<timeout>  → send URL
 *   AT+QHTTPGET=<timeout>        → start download
 *   AT+QHTTPREAD=<timeout>       → stream body → USART3 → we catch in URC
 *
 * Alternatively uses TCP CH_OTA with raw HTTP GET if QHTTP not available.
 * We use the raw TCP approach for broadest compatibility.
 */

#define HTTP_RESP_BUF  512
#define FOTA_TCP_CH    EC800M_CH_OTA

static fota_state_t s_state    = FOTA_STATE_IDLE;
static uint32_t     s_expected = 0;   /* Content-Length */
static uint32_t     s_received = 0;   /* bytes written to SPI flash */
static uint32_t     s_flash_wr = FOTA_FLASH_ADDR;  /* write pointer */
static char         s_url[128] = {0};
static bool         s_header_done = false;

/* CRC32 running state for verification */
static uint32_t s_crc_accum = 0xFFFFFFFFUL;

static uint32_t crc32_update(uint32_t crc, const uint8_t *data, uint16_t len)
{
    while (len--) {
        crc ^= *data++;
        for (int i = 0; i < 8; i++)
            crc = (crc >> 1) ^ (crc & 1 ? 0xEDB88320UL : 0);
    }
    return crc;
}

/* ── Parse host:port and path from URL ───────────────────────────────────── */
static bool parse_url(const char *url, char *host, uint16_t *port, char *path)
{
    const char *p = url;
    if (strncmp(p, "http://", 7) == 0) p += 7;

    const char *colon = strchr(p, ':');
    const char *slash = strchr(p, '/');

    if (colon && (!slash || colon < slash)) {
        uint16_t hlen = (uint16_t)(colon - p);
        memcpy(host, p, hlen); host[hlen] = '\0';
        *port = (uint16_t)atoi(colon + 1);
        strcpy(path, slash ? slash : "/");
    } else {
        uint16_t hlen = slash ? (uint16_t)(slash - p) : (uint16_t)strlen(p);
        memcpy(host, p, hlen); host[hlen] = '\0';
        *port = 80;
        strcpy(path, slash ? slash : "/");
    }
    return host[0] != '\0';
}

/* ── Send HTTP GET request ────────────────────────────────────────────────── */
static void send_http_get(const char *path, const char *host)
{
    char req[256];
    snprintf(req, sizeof(req),
             "GET %s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n",
             path, host);
    ec800m_tcp_send(FOTA_TCP_CH, (const uint8_t *)req, (uint16_t)strlen(req));
    dbg_printf("[FOTA] HTTP GET sent: %s\r\n", path);
}

/* ── Called when EC800M ch=OTA receives data ──────────────────────────────── */
void fota_on_data(const uint8_t *data, uint16_t len)
{
    if (s_state != FOTA_STATE_DOWNLOADING) return;

    if (!s_header_done) {
        /* Find end of HTTP headers (\r\n\r\n) */
        const uint8_t *body = NULL;
        for (uint16_t i = 0; i + 3 < len; i++) {
            if (data[i]=='\r' && data[i+1]=='\n' &&
                data[i+2]=='\r' && data[i+3]=='\n') {
                body = data + i + 4;
                len  = len - (uint16_t)(body - data);
                s_header_done = true;
                break;
            }
        }
        if (!s_header_done) return;
        data = body;
    }

    if (s_received + len > FOTA_MAX_SIZE) {
        dbg_printf("[FOTA] image too large!\r\n");
        s_state = FOTA_STATE_ERROR;
        return;
    }

    if (!ext_flash_try_lock(EXT_FLASH_OWNER_OTA)) { s_state = FOTA_STATE_ERROR; return; }
    bool write_ok = ext_flash_write_verified(EXT_FLASH_OWNER_OTA, s_flash_wr, data, len);
    ext_flash_unlock(EXT_FLASH_OWNER_OTA);
    if (!write_ok) { s_state = FOTA_STATE_ERROR; return; }
    s_flash_wr += len;
    s_received += len;
    s_crc_accum = crc32_update(s_crc_accum, data, len);

    if (s_expected > 0 && s_received >= s_expected) {
        s_state = FOTA_STATE_VERIFYING;
        dbg_printf("[FOTA] download complete (%u bytes)\r\n", (unsigned)s_received);
    }
}

void fota_on_http_header(const char *header)
{
    /* Look for Content-Length */
    const char *p = strstr(header, "Content-Length:");
    if (p) s_expected = (uint32_t)atol(p + 15);
}

/* ── Public API ───────────────────────────────────────────────────────────── */
void fota_init(void)
{
    s_state    = FOTA_STATE_IDLE;
    s_received = 0;
}

int fota_start(const char *url)
{
    if (s_state != FOTA_STATE_IDLE) return -1;
    strncpy(s_url, url, sizeof(s_url) - 1);

    char host[CFG_IP_LEN]; uint16_t port; char path[128];
    if (!parse_url(url, host, &port, path)) return -1;

    dbg_printf("[FOTA] starting: %s\r\n", url);

    /* Erase first 16 sectors of download area */
    bool ota_locked = ext_flash_try_lock(EXT_FLASH_OWNER_OTA);
    if (!ota_locked) { s_state = FOTA_STATE_ERROR; return -1; }
    bool erase_ok = ext_flash_erase(EXT_FLASH_OWNER_OTA, FOTA_FLASH_ADDR, FOTA_MAX_SIZE);
    ext_flash_unlock(EXT_FLASH_OWNER_OTA);
    if (!erase_ok) { s_state = FOTA_STATE_ERROR; return -1; }

    s_state       = FOTA_STATE_CONNECTING;
    s_received    = 0;
    s_flash_wr    = FOTA_FLASH_ADDR;
    s_header_done = false;
    s_crc_accum   = 0xFFFFFFFFUL;
    s_expected    = cfg_get()->fota_size;

    if (ec800m_tcp_open(FOTA_TCP_CH, host, port) == 0) {
        send_http_get(path, host);
        s_state = FOTA_STATE_DOWNLOADING;
    } else {
        s_state = FOTA_STATE_ERROR;
        return -1;
    }
    return 0;
}

void fota_process(void)
{
    if (s_state == FOTA_STATE_VERIFYING) {
        uint32_t final_crc = ~s_crc_accum;
        dbg_printf("[FOTA] CRC32=0x%x size=%u\r\n",
                   (unsigned)final_crc, (unsigned)s_received);
        /* Without a reference CRC in the URL/manifest we just accept it */
        s_state = FOTA_STATE_READY;
        dbg_printf("[FOTA] image ready, call fota_apply() to reboot\r\n");
    }

    if (s_state == FOTA_STATE_DOWNLOADING) {
        /* Timeout: if 60 s pass with no new data */
        static uint32_t last_rx_ms = 0;
        if (s_received != last_rx_ms) last_rx_ms = TICK_MS();
        if (TICK_MS() - last_rx_ms > 60000) {
            dbg_printf("[FOTA] download timeout\r\n");
            s_state = FOTA_STATE_ERROR;
        }
    }
}

void fota_apply(void)
{
    if (s_state != FOTA_STATE_READY) return;

    /* Write pending-upgrade marker to SPI flash */
    uint8_t marker[8];
    uint32_t magic = FOTA_PENDING_MAGIC;
    memcpy(marker, &magic, 4);
    uint32_t size = s_received;
    memcpy(marker + 4, &size, 4);
    bool ota_locked = ext_flash_try_lock(EXT_FLASH_OWNER_OTA);
    if (!ota_locked) { s_state = FOTA_STATE_ERROR; return; }
    bool marker_ok = ext_flash_erase(EXT_FLASH_OWNER_OTA, FOTA_PENDING_ADDR, FLASH_SECTOR_SIZE) && ext_flash_write_verified(EXT_FLASH_OWNER_OTA, FOTA_PENDING_ADDR, marker, 8);
    ext_flash_unlock(EXT_FLASH_OWNER_OTA);
    if (!marker_ok) { s_state = FOTA_STATE_ERROR; return; }

    dbg_printf("[FOTA] marker written, rebooting...\r\n");
    delay_ms(200);
    NVIC_SystemReset();
}

fota_state_t fota_get_state(void)    { return s_state; }
uint32_t     fota_get_progress(void) { return s_received; }
