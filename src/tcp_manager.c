#include "tcp_manager.h"
#include "ec800m.h"
#include "flash_config.h"
#include "debug_uart.h"
#include "hw_init.h"
#include "config.h"
#include "fota.h"

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

    if (ip[0] == '\0' || ip[0] == '0') {
        c->state = CS_DISABLED;
        return;
    }

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

    switch (c->state) {
    case CS_WAIT_MODEM:
        if (ec800m_is_ready())
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
        if (!ec800m_is_ready()) {
            c->state    = CS_WAIT_MODEM;
            c->state_ms = TICK_MS();
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
    ch_init(&s_ch[0], TCP_CH_MAIN);
    ch_init(&s_ch[1], TCP_CH_BACKUP);
}

void tcp_manager_process(void)
{
    ch_process(&s_ch[0]);
    ch_process(&s_ch[1]);
}

void tcp_manager_reconnect(void)
{
    ec800m_tcp_close(TCP_CH_MAIN);
    ec800m_tcp_close(TCP_CH_BACKUP);
    ch_init(&s_ch[0], TCP_CH_MAIN);
    ch_init(&s_ch[1], TCP_CH_BACKUP);
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
bool tcp_manager_ota_active(void){fota_state_t s=fota_get_state();return s==FOTA_STATE_CONNECTING||s==FOTA_STATE_DOWNLOADING||s==FOTA_STATE_VERIFYING;}
