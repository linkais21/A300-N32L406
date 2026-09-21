#include "cfg_query.h"
#include "service_workspace.h"
#include "ec800m.h"
#include "flash_config.h"
#include "work_mode.h"
#include "config.h"
#include "work_mode_sleep.h"
#include <string.h>

static uint8_t s_flags;
#define CFGQ_BUSY 1U
#define CFGQ_DONE 2U
static int16_t s_result;
static bool s_started;
static uint8_t cfg_query_checksum(const uint8_t *data, uint16_t length)
{ uint8_t c = 0U; while (length--) c ^= *data++; return c; }
static bool cfg_query_id(uint8_t out[8])
{
    char imei[16]; uint8_t i;
    ec800m_get_imei(imei, sizeof imei);
    for (i = 0U; i < 15U; ++i) if (imei[i] < '0' || imei[i] > '9') return false;
    for (i = 0U; i < 7U; ++i)
        out[i] = (uint8_t)(((imei[i * 2U] - '0') << 4) | (imei[i * 2U + 1U] - '0'));
    out[7] = (uint8_t)((imei[14] - '0') << 4);
    return true;
}
static bool cfg_query_parse_92(const uint8_t *p, uint16_t n, const uint8_t id[8])
{
    uint16_t len;
    if (!p || n < 16U || p[0] != 0x66U || p[1] != 0x66U || p[2] != 0x92U || p[n-1U] != 0x0dU) return false;
    len = (uint16_t)(((uint16_t)p[3] << 8) | p[4]);
    if (len < 9U || (uint16_t)(len + 7U) != n || memcmp(&p[5], id, 8U) != 0) return false;
    return cfg_query_checksum(p, (uint16_t)(n - 2U)) == p[n - 2U];
}
/* A live modem transaction retains workspace pointers; initialization must
 * not invalidate them. Normal completion drains it before releasing owner. */
void cfg_query_init(void) { if (s_started) return; s_flags = 0U; s_result = -1; }
int cfg_query_start(void) { if ((s_flags & CFGQ_BUSY) || !ec800m_is_ready()) return -1; s_flags = CFGQ_BUSY; return 0; }
void cfg_query_process(void)
{
    size_t cap; uint8_t *buf, *req;
    if (!(s_flags & CFGQ_BUSY)) return;
    if (!s_started && !service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_DIAGNOSTIC)) return;
    buf = service_workspace_buffer(&cap);
    /* Reserve the tail for TX until the asynchronous transaction completes.
     * RX and TX cannot alias, even when the response fills its capacity. */
    req = buf + cap - 16U;
    if (!s_started) {
        if (!cfg_query_id(&req[5])) { s_result = -1; goto done; }
        req[0] = 0x66U; req[1] = 0x66U; req[2] = 0x13U;
        req[3] = 0U; req[4] = 9U; req[13] = 0U;
        req[14] = cfg_query_checksum(req, 14U); req[15] = 0x0dU;
        if (ec800m_udp_txn_start(CFG_QUERY_HOST, CFG_QUERY_PORT, req, 16U,
                                 buf, (uint16_t)(cap - 16U), 8000U) != 0) {
            s_result = -1; goto done;
        }
        s_started = true; return;
    }
    ec800m_udp_txn_process();
    s_result = ec800m_udp_txn_result();
    if (s_result == -2) return;
    s_started = false;
    if (s_result > 0 && (uint16_t)s_result <= cap - 16U &&
        cfg_query_parse_92(buf, (uint16_t)s_result, &req[5])) {
        req[2] = 0x14U;
        req[14] = cfg_query_checksum(req, 14U);
        (void)ec800m_udp_send_once(CFG_QUERY_HOST, CFG_QUERY_PORT, req, 16U);
        work_mode_config_changed(cfg_get(), TICK_MS() / 1000U);
        s_result = 0;
    } else s_result = -1;
done:
    service_workspace_release(SERVICE_WORKSPACE_OWNER_DIAGNOSTIC);
    s_flags = CFGQ_DONE;
}
bool cfg_query_is_busy(void) { return (s_flags & CFGQ_BUSY) != 0U; }
bool cfg_query_take_result(int *result) { if (!(s_flags & CFGQ_DONE)) return false; if (result) *result = s_result; s_flags = 0U; return true; }
