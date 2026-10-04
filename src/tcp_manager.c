#include "tcp_manager.h"
#include "ec800m.h"
#include "flash_config.h"
#include "debug_uart.h"
#include "hw_init.h"
#include "config.h"
#include "fota.h"
#include <string.h>

/*
 * Dual-server mode: both main and backup connect independently.
 * Each channel retries with exponential backoff on its own.
 * send_frame() in jt808.c broadcasts to all open channels.
 */

#define BACKOFF_INIT_MS   5000
#define BACKOFF_MAX_MS    120000
#define CONNECT_TIMEOUT_MS 15000
#define MAX_FAILS          5

typedef enum {
    CS_WAIT_MODEM = 0,
    CS_CONNECTING,
    CS_ONLINE,
    CS_BACKOFF,
    CS_DISABLED,
} ch_state_t;

typedef struct {
    ch_state_t state;
    uint32_t   state_ms;
    uint32_t   backoff_ms;
    uint8_t    fails;
    uint8_t    ch;
    uint32_t   generation;
} ch_ctx_t;

static ch_ctx_t s_ch[2];   /* [0]=main  [1]=backup */
static bool s_boot_summary_logged;
static uint8_t s_reconnect_pending;

static bool decimal_length_valid(const char *value, size_t first, size_t second)
{
    size_t length = 0U;
    if (value == NULL) return false;
    while (value[length] >= '0' && value[length] <= '9') ++length;
    return value[length] == '\0' && (length == first || length == second);
}

static bool iccid_length_valid(const char *value)
{
    size_t length = 0U;
    if (value == NULL) return false;
    while ((value[length] >= '0' && value[length] <= '9') ||
           (value[length] >= 'A' && value[length] <= 'F'))
        ++length;
    return value[length] == '\0' && (length == 19U || length == 20U);
}

static void log_boot_summary(void)
{
    char imei[16] = {0};
    char iccid[22] = {0};
    char derived_pid[12] = {0};
    const char *pid;
    device_config_t *cfg;
    size_t imei_length, iccid_length;
    bool imei_valid, iccid_valid;
    if (s_boot_summary_logged) return;
    cfg = cfg_get();
    if (cfg == NULL) return;
    ec800m_get_imei(imei, sizeof imei);
    ec800m_get_iccid(iccid, sizeof iccid);
    imei_length = strlen(imei);
    iccid_length = strlen(iccid);
    imei_valid = decimal_length_valid(imei, 15U, 15U);
    iccid_valid = iccid_length_valid(iccid);
    pid = cfg->pid;
    if (!decimal_length_valid(pid, 11U, 11U) && imei_valid) {
        memcpy(derived_pid, imei + 4U, 11U);
        derived_pid[11] = '\0';
        pid = derived_pid;
    }
    if (!decimal_length_valid(pid, 11U, 11U)) pid = "INVALID";
    if (imei_valid && iccid_valid)
        dbg_printf("[BOOT-ID] IMEI=%s PID=%s ICCID=%s\r\n", imei, pid, iccid);
    else if (!imei_valid && !iccid_valid)
        dbg_printf("[BOOT-ID] IMEI=INVALID(len=%u) PID=%s ICCID=INVALID(len=%u)\r\n",
                   (unsigned)imei_length, pid, (unsigned)iccid_length);
    else if (!imei_valid)
        dbg_printf("[BOOT-ID] IMEI=INVALID(len=%u) PID=%s ICCID=%s\r\n",
                   (unsigned)imei_length, pid, iccid);
    else
        dbg_printf("[BOOT-ID] IMEI=%s PID=%s ICCID=INVALID(len=%u)\r\n",
                   imei, pid, (unsigned)iccid_length);
    if (cfg->backup_ip[0] == '\0' || cfg->backup_port == 0U)
        dbg_printf("[BOOT-SERVER] MAIN=%s:%u BACKUP=OFF\r\n",
                   cfg->server_ip, (unsigned)cfg->server_port);
    else
        dbg_printf("[BOOT-SERVER] MAIN=%s:%u BACKUP=%s:%u\r\n",
                   cfg->server_ip, (unsigned)cfg->server_port,
                   cfg->backup_ip, (unsigned)cfg->backup_port);
    s_boot_summary_logged = true;
}

static void ch_init(ch_ctx_t *c, uint8_t ch)
{
    c->ch         = ch;
    c->state      = CS_WAIT_MODEM;
    c->state_ms   = TICK_MS();
    c->backoff_ms = BACKOFF_INIT_MS;
    c->fails      = 0;
    c->generation = 0U;
}

static void ch_start_connect(ch_ctx_t *c)
{
    device_config_t *cfg = cfg_get();
    const char *ip   = (c->ch == TCP_CH_MAIN) ? cfg->server_ip  : cfg->backup_ip;
    uint16_t    port = (c->ch == TCP_CH_MAIN) ? cfg->server_port : cfg->backup_port;

    if (!ec800m_is_ready() || !ec800m_identity_ready()) {
        c->state = CS_WAIT_MODEM;
        c->state_ms = TICK_MS();
        return;
    }

    if (ip[0] == '\0' || port == 0U) {
        c->state = CS_DISABLED;
        return;
    }

    log_boot_summary();
    dbg_printf("[TCP] ch%u connecting -> %s:%u\r\n", c->ch, ip, port);
    ec800m_tcp_open(c->ch, ip, port);
    c->state    = CS_CONNECTING;
    c->state_ms = TICK_MS();
}

static void ch_on_fail(ch_ctx_t *c)
{
    ec800m_tcp_close(c->ch);
    c->fails++;
    dbg_printf("[TCP] ch%u fail #%u backoff %ums\r\n",
               c->ch, c->fails, (unsigned)c->backoff_ms);
    if (c->fails >= MAX_FAILS) {
        /* after too many failures, keep retrying at max interval */
        c->fails = 0;
    }
    c->state    = CS_BACKOFF;
    c->state_ms = TICK_MS();
}

static void ch_process(ch_ctx_t *c)
{
    if (c->state == CS_DISABLED) return;
    if ((!ec800m_is_ready() || !ec800m_identity_ready()) &&
        c->state != CS_WAIT_MODEM) {
        if (c->state == CS_CONNECTING || c->state == CS_ONLINE)
            ec800m_tcp_close(c->ch);
        c->state = CS_WAIT_MODEM;
        c->state_ms = TICK_MS();
        return;
    }

    switch (c->state) {
    case CS_WAIT_MODEM:
        if (ec800m_is_ready() && ec800m_identity_ready())
            ch_start_connect(c);
        break;

    case CS_CONNECTING: {
        tcp_state_t st = ec800m_tcp_state(c->ch);
        if (st == TCP_STATE_OPEN) {
            ++c->generation;
            dbg_printf("[TCP] ch%u online\r\n", c->ch);
            c->state      = CS_ONLINE;
            c->state_ms   = TICK_MS();
            c->backoff_ms = BACKOFF_INIT_MS;
            c->fails      = 0;
        } else if (st == TCP_STATE_ERROR ||
                   TICK_MS() - c->state_ms > CONNECT_TIMEOUT_MS) {
            ch_on_fail(c);
        }
        break;
    }

    case CS_ONLINE: {
        tcp_state_t st = ec800m_tcp_state(c->ch);
        if (st != TCP_STATE_OPEN) {
            dbg_printf("[TCP] ch%u dropped\r\n", c->ch);
            ch_on_fail(c);
        }
        break;
    }

    case CS_BACKOFF:
        if (TICK_MS() - c->state_ms >= c->backoff_ms) {
            c->backoff_ms *= 2;
            if (c->backoff_ms > BACKOFF_MAX_MS)
                c->backoff_ms = BACKOFF_MAX_MS;
            ch_start_connect(c);
        }
        break;

    default:
        break;
    }
}

void tcp_manager_init(void)
{
    s_boot_summary_logged = false;
    s_reconnect_pending = false;
    ch_init(&s_ch[0], TCP_CH_MAIN);
    ch_init(&s_ch[1], TCP_CH_BACKUP);
}

void tcp_manager_process(void)
{
    /* OTA owns modem control. Pause connect/close/recovery without invalidating
     * established JT808 sessions; their data path runs independently. */
    if (tcp_manager_ota_active()) return;
    if (s_reconnect_pending) tcp_manager_reconnect_channels(s_reconnect_pending);
    ch_process(&s_ch[0]);
    ch_process(&s_ch[1]);
}

void tcp_manager_request_reconnect(void)
{
    s_reconnect_pending |= (1U << TCP_CH_MAIN) | (1U << TCP_CH_BACKUP);
}

void tcp_manager_reconnect(void)
{
    tcp_manager_reconnect_channels((1U << TCP_CH_MAIN) | (1U << TCP_CH_BACKUP));
}

void tcp_manager_reconnect_channels(uint8_t channel_mask)
{
    s_reconnect_pending |= channel_mask & ((1U << TCP_CH_MAIN) | (1U << TCP_CH_BACKUP));
    if (tcp_manager_ota_active()) {
        /* Retain config-triggered reconnects and apply the latest endpoints
         * once OTA releases control. Repeated requests coalesce here. */
        return;
    }
    channel_mask = s_reconnect_pending;
    s_reconnect_pending = false;
    for (uint8_t i = 0U; i < 2U; ++i) {
        uint8_t ch = s_ch[i].ch;
        if ((channel_mask & (1U << ch)) == 0U) continue;
        uint32_t generation = s_ch[i].generation;
        ec800m_tcp_close(ch);
        ch_init(&s_ch[i], ch);
        s_ch[i].generation = generation;
    }
}

bool tcp_manager_is_online(void)
{
    return s_ch[0].state == CS_ONLINE || s_ch[1].state == CS_ONLINE;
}

bool tcp_manager_ch_online(uint8_t ch)
{
    if (ch == TCP_CH_MAIN)   return s_ch[0].state == CS_ONLINE;
    if (ch == TCP_CH_BACKUP) return s_ch[1].state == CS_ONLINE;
    return false;
}

uint32_t tcp_manager_session_generation(uint8_t ch)
{
    if (ch == TCP_CH_MAIN) return s_ch[0].generation;
    if (ch == TCP_CH_BACKUP) return s_ch[1].generation;
    return 0U;
}

uint8_t tcp_manager_active_ch(void)
{
    if (s_ch[0].state == CS_ONLINE) return TCP_CH_MAIN;
    if (s_ch[1].state == CS_ONLINE) return TCP_CH_BACKUP;
    return TCP_CH_MAIN;
}
bool tcp_manager_ota_active(void)
{
    return fota_is_active();
}
