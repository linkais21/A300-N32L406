#include "tcp_manager.h"
#include "ec800m.h"
#include "flash_config.h"
#include "debug_uart.h"
#include "hw_init.h"
#include "config.h"

/*
 * Reconnect strategy:
 *   Attempt main server up to MAX_MAIN_FAILS times.
 *   On each failure, backoff doubles: 5s → 10s → 20s → 40s → cap at 120s.
 *   After MAX_MAIN_FAILS, try backup server with same backoff.
 *   After MAX_BACKUP_FAILS, reset modem and start over.
 */

#define MAX_MAIN_FAILS    3
#define MAX_BACKUP_FAILS  3
#define BACKOFF_INIT_MS   5000
#define BACKOFF_MAX_MS    120000

typedef enum {
    TM_STATE_WAIT_MODEM = 0,
    TM_STATE_CONNECTING,
    TM_STATE_ONLINE,
    TM_STATE_BACKOFF,
    TM_STATE_TRY_BACKUP,
    TM_STATE_RESET_MODEM,
} tm_state_t;

static tm_state_t s_state        = TM_STATE_WAIT_MODEM;
static uint32_t   s_state_ms     = 0;
static uint8_t    s_main_fails   = 0;
static uint8_t    s_backup_fails = 0;
static uint32_t   s_backoff_ms   = BACKOFF_INIT_MS;
static bool       s_using_backup = false;
static uint8_t    s_active_ch    = TCP_CH_MAIN;

static void start_connect(void)
{
    device_config_t *c = cfg_get();
    const char *ip;
    uint16_t port;
    uint8_t ch;

    if (!s_using_backup) {
        ip   = c->server_ip;
        port = c->server_port;
        ch   = TCP_CH_MAIN;
    } else {
        ip   = c->backup_ip;
        port = c->backup_port;
        ch   = TCP_CH_BACKUP;
    }

    dbg_printf("[TCP] connecting ch%u → %s:%u\r\n", ch, ip, port);
    ec800m_tcp_open(ch, ip, port);
    s_active_ch  = ch;
    s_state      = TM_STATE_CONNECTING;
    s_state_ms   = TICK_MS();
}

static void on_connect_fail(void)
{
    ec800m_tcp_close(s_active_ch);

    if (!s_using_backup) {
        s_main_fails++;
        dbg_printf("[TCP] main fail #%u\r\n", s_main_fails);
        if (s_main_fails >= MAX_MAIN_FAILS) {
            s_using_backup = true;
            s_main_fails   = 0;
            s_backoff_ms   = BACKOFF_INIT_MS;
        }
    } else {
        s_backup_fails++;
        dbg_printf("[TCP] backup fail #%u\r\n", s_backup_fails);
        if (s_backup_fails >= MAX_BACKUP_FAILS) {
            dbg_printf("[TCP] all servers failed, reset modem\r\n");
            s_state        = TM_STATE_RESET_MODEM;
            s_state_ms     = TICK_MS();
            s_backup_fails = 0;
            s_using_backup = false;
            s_backoff_ms   = BACKOFF_INIT_MS;
            return;
        }
    }

    s_state    = TM_STATE_BACKOFF;
    s_state_ms = TICK_MS();
    dbg_printf("[TCP] backoff %u ms\r\n", (unsigned)s_backoff_ms);
}

void tcp_manager_init(void)
{
    s_state        = TM_STATE_WAIT_MODEM;
    s_state_ms     = TICK_MS();
    s_main_fails   = 0;
    s_backup_fails = 0;
    s_backoff_ms   = BACKOFF_INIT_MS;
    s_using_backup = false;
}

void tcp_manager_process(void)
{
    switch (s_state) {
    case TM_STATE_WAIT_MODEM:
        if (ec800m_is_ready()) {
            s_main_fails   = 0;
            s_backup_fails = 0;
            s_using_backup = false;
            s_backoff_ms   = BACKOFF_INIT_MS;
            start_connect();
        }
        break;

    case TM_STATE_CONNECTING: {
        tcp_state_t st = ec800m_tcp_state(s_active_ch);
        if (st == TCP_STATE_OPEN) {
            dbg_printf("[TCP] ch%u online\r\n", s_active_ch);
            s_state      = TM_STATE_ONLINE;
            s_state_ms   = TICK_MS();
            s_backoff_ms = BACKOFF_INIT_MS;  /* reset on success */
        } else if (st == TCP_STATE_ERROR ||
                   TICK_MS() - s_state_ms > 15000) {
            on_connect_fail();
        }
        break;
    }

    case TM_STATE_ONLINE: {
        tcp_state_t st = ec800m_tcp_state(s_active_ch);
        if (st != TCP_STATE_OPEN) {
            dbg_printf("[TCP] ch%u dropped\r\n", s_active_ch);
            on_connect_fail();
        }
        /* If modem lost network, restart registration */
        if (!ec800m_is_ready()) {
            s_state    = TM_STATE_WAIT_MODEM;
            s_state_ms = TICK_MS();
        }
        break;
    }

    case TM_STATE_BACKOFF:
        if (TICK_MS() - s_state_ms >= s_backoff_ms) {
            /* Double backoff, capped */
            s_backoff_ms *= 2;
            if (s_backoff_ms > BACKOFF_MAX_MS)
                s_backoff_ms = BACKOFF_MAX_MS;
            start_connect();
        }
        break;

    case TM_STATE_RESET_MODEM:
        if (TICK_MS() - s_state_ms > 5000) {
            dbg_printf("[TCP] resetting modem\r\n");
            ec800m_reset();
            s_state    = TM_STATE_WAIT_MODEM;
            s_state_ms = TICK_MS();
        }
        break;

    case TM_STATE_TRY_BACKUP:
        /* Reserved state — failover is handled inline in on_connect_fail(). */
        start_connect();
        break;
    }
}

void tcp_manager_reconnect(void)
{
    ec800m_tcp_close(TCP_CH_MAIN);
    ec800m_tcp_close(TCP_CH_BACKUP);
    s_using_backup = false;
    s_main_fails   = 0;
    s_backup_fails = 0;
    s_backoff_ms   = BACKOFF_INIT_MS;
    s_state        = TM_STATE_WAIT_MODEM;
    s_state_ms     = TICK_MS();
}

bool    tcp_manager_is_online(void)    { return s_state == TM_STATE_ONLINE; }
uint8_t tcp_manager_active_ch(void)    { return s_active_ch; }
