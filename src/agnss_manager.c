#include "agnss_manager.h"
#include "agnss_online.h"
#include "agnss_storage.h"
#include "agnss_vendor.h"
#include "ec800m.h"
#include "gps.h"
#include "fota.h"
#include "config.h"
#include "debug_uart.h"
#include <stddef.h>
#ifdef A300_HARDWARE_BRINGUP
void agnss_init(gnss_type_t t) { (void)t; }
bool agnss_has_injected(void) { return false; }
bool agnss_retry_due(uint32_t now) { (void)now; return false; }
void agnss_process(void) {}
#else
#define AGNSS_REFRESH_MS (2UL * 60UL * 60UL * 1000UL)
#define AGNSS_RETRY_MS 60000UL
static gnss_type_t s_type, s_meta_type;
static bool s_boot_pending, s_injected;
static uint32_t s_last_attempt, s_retry_at, s_off, s_meta_seq, s_meta_len, s_meta_crc;

void agnss_init(gnss_type_t t)
{
    agnss_online_reset();
    s_type = t;
    s_boot_pending = true;
    s_injected = false;
    s_last_attempt = 0;
    s_retry_at = 0;
    s_off = 0;
    gnss_vendor_set_type(t);
    (void)agnss_storage_init();
}

bool agnss_has_injected(void)
{
    return s_injected || agnss_online_has_injected();
}

bool agnss_retry_due(uint32_t now)
{
    return (int32_t)(now - s_retry_at) >= 0;
}

void agnss_process(void)
{
    if(agnss_online_process(s_type))return;
    uint32_t now = TICK_MS();
    agnss_meta_t m;
    uint16_t cap, n;
    uint8_t *buf;
    uint8_t failure = 1;
    if (s_type != GNSS_TYPE_TAU804M || fota_is_active() || !ec800m_is_ready()) return;
    if (!s_boot_pending &&
        (gps_is_valid() || (uint32_t)(now - s_last_attempt) < AGNSS_REFRESH_MS)) return;
    if (!agnss_retry_due(now)) return;

    /* Pin the validated payload; restart the offset only for a new identity. */
    if (!agnss_storage_read_open(&m) || m.type != (uint8_t)s_type) goto retry;
    if (m.sequence != s_meta_seq || m.length != s_meta_len ||
        m.type != s_meta_type || m.crc32 != s_meta_crc) {
        s_meta_seq = m.sequence;
        s_meta_len = m.length;
        s_meta_type = (gnss_type_t)m.type;
        s_meta_crc = m.crc32;
        s_off = 0;
        s_injected = false;
    }
    /* Completion is acknowledged separately from the last data block. */
    if (s_off >= m.length) {
        if (!gnss_vendor_inject(s_type, NULL, 0)) {
            if (gnss_vendor_inject_pending()) return;
            failure = 2; goto retry;
        }
        agnss_storage_read_close();
        dbg_printf("[AGNSS-CACHE] tx_done=1 bytes=%lu\r\n", (unsigned long)m.length);
        s_off = 0;
        s_boot_pending = false;
        s_injected = true;
        s_last_attempt = now;
        return;
    }
    buf = agnss_storage_scratch(&cap);
    n = (uint16_t)((m.length - s_off) > cap ? cap : (m.length - s_off));
    if (!agnss_storage_read_chunk(s_off, buf, n)) {
        failure = 3;
        goto retry;
    }
    if (!gnss_vendor_inject(s_type, buf, n)) {
        if (gnss_vendor_inject_pending()) return;
        failure = 4;
        goto retry;
    }
    s_off += n;
    return;
retry:
    agnss_storage_read_close();
    dbg_printf("[AGNSS-CACHE] tx_done=0 reason=%u off=%lu\r\n",
               (unsigned)failure, (unsigned long)s_off);
    s_retry_at = now + AGNSS_RETRY_MS;
}
#endif
