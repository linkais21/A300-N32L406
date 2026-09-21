#include "cfg_query.h"
#include "service_workspace.h"
#include "ec800m.h"
#include "at_config.h"
#include "debug_uart.h"
#include "config.h"
#include "work_mode_sleep.h"
#include <string.h>

static uint8_t s_flags;
#define CFGQ_BUSY 1U
#define CFGQ_DONE 2U
static int16_t s_result;
static bool s_started;
static uint8_t s_attempts;
static uint8_t cfg_query_checksum(const uint8_t *data, uint16_t length)
{ uint8_t c = 0U; while (length--) c ^= *data++; return c; }
static bool cfg_query_id(uint8_t out[8])
{
    char imei[16]; uint8_t i;
    ec800m_get_imei(imei, sizeof imei);
    for (i = 0U; i < 15U; ++i) if (imei[i] < '0' || imei[i] > '9') return false;
    /* Protocol uses a leading zero nibble followed by the 15 IMEI digits. */
    out[0] = (uint8_t)(imei[0] - '0');
    for (i = 0U; i < 7U; ++i)
        out[i + 1U] = (uint8_t)(((imei[i * 2U + 1U] - '0') << 4) |
                                (imei[i * 2U + 2U] - '0'));
    return true;
}

static void cfg_query_ack(bool success, void *context)
{
    uint8_t *req = context;
    if (!success) return;
    /* Persistence has succeeded; confirm before APN/IP effects tear down
     * this transport. Keep failure visible so platform redelivery can retry. */
    req[2] = 0x14U;
    req[14] = cfg_query_checksum(req, 14U);
    s_result = ec800m_udp_send_once(CFG_QUERY_HOST, CFG_QUERY_PORT, req, 16U) == 0 ? 0 : -1;
}

static int cfg_query_apply(const uint8_t *p, uint16_t n, uint8_t *req)
{
    /* DATA begins with has-config, then type/name(10)/value.  Pass is the
     * platform's one-shot SMS command container (for example hbt,120#). */
    static const uint8_t name[10] = {'P','a','s','s'};
    if (n == 1U && p[0] == 0U) {
        dbg_printf("[CFGQ] pending=0\r\n");
        return 0;
    }
    /* Exactly one Pass; combine parameter writes using atomic DUALSET.
     * Reject trailing/unknown fields before executing any side effects. */
    if (n < 14U || p[0] != 1U || p[1] != 3U ||
        memcmp(p + 2U, name, sizeof name) != 0 || p[12U] != n - 13U)
    {
        dbg_printf("[CFGQ] reject=PASS_SHAPE bytes=%u\r\n", (unsigned)n);
        return -1;
    }
    p += 13U; n -= 13U;
    if (n >= 2U && p[0] == '"' && p[n-1U] == '"') { ++p; n -= 2U; }
    if (n && p[n-1U] == '#') --n;
    bool accepted = n && at_config_execute_text_command_ack(p, n, cfg_query_ack, req);
    /* Never print Pass itself: it may contain APN credentials or a device key. */
    dbg_printf("[CFGQ] pass_bytes=%u accepted=%u\r\n", (unsigned)n, accepted ? 1U : 0U);
    return accepted ? 1 : -1;
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
int cfg_query_start(void) { if ((s_flags & CFGQ_BUSY) || !ec800m_is_ready()) return -1; s_flags = CFGQ_BUSY; s_attempts = 0U; return 0; }
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
                                 buf, 384U, 8000U) != 0) {
            s_result = -1; goto done;
        }
        ++s_attempts; s_started = true; return;
    }
    ec800m_udp_txn_process();
    s_result = ec800m_udp_txn_result();
    if (s_result == -2) return;
    s_started = false;
    if (s_result <= 0 && s_attempts < 3U) {
        service_workspace_release(SERVICE_WORKSPACE_OWNER_DIAGNOSTIC);
        return;
    }
    if (s_result > 0 && (uint16_t)s_result <= cap - 16U &&
        cfg_query_parse_92(buf, (uint16_t)s_result, &req[5])) {
        uint16_t data_len = (uint16_t)(((uint16_t)buf[3] << 8) | buf[4]);
        uint16_t payload_len = data_len >= 8U ? (uint16_t)(data_len - 8U) : 0U;
        int applied = payload_len ? cfg_query_apply(buf + 13U, payload_len, req) : 0;
        if (applied <= 0) { s_result = (int16_t)applied; goto done; }
    } else s_result = -1;
done:
    dbg_printf("[CFGQ] result=%d\r\n", (int)s_result);
    service_workspace_release(SERVICE_WORKSPACE_OWNER_DIAGNOSTIC);
    s_flags = CFGQ_DONE;
}
bool cfg_query_is_busy(void) { return (s_flags & CFGQ_BUSY) != 0U; }
bool cfg_query_take_result(int *result) { if (!(s_flags & CFGQ_DONE)) return false; if (result) *result = s_result; s_flags = 0U; return true; }
