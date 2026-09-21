#include "log_platform.h"
#include "service_workspace.h"
#include "ec800m.h"
#include "jt808.h"
#include "fota.h"
#include "work_mode_sleep.h"
#include "work_mode.h"
#include "gps.h"
#include "config.h"
#include "debug_uart.h"
#include "build_version.h"
#include <stdio.h>
#include <string.h>

/* UINT32_MAX is the pending-event sentinel; keeps state to one word. */
static uint32_t s_last_ms;

static uint16_t build_log(uint8_t *buf, uint16_t cap)
{
    char imei[16];
    if (!buf || cap < 64U) return 0U;
    ec800m_get_imei(imei, sizeof imei);
    if (!imei[0]) return 0U;
    return (uint16_t)snprintf((char *)buf, cap,
        "<LOG*%s*U:%s,%u*R:000000*C:%d*3G:%s*3I:%u*3L:00*3T:1*3W:%s:%u*3X:%s:%u*4C:0*4F:1*62:%u,%u,%u,%u*6F:0*74:%u>",
        imei, cfg_get()->server_ip, (unsigned)cfg_get()->server_port,
        ec800m_get_csq(), FW_FULL_VERSION,
        gps_is_valid() ? 1U : 0U,
        cfg_get()->server_ip, (unsigned)cfg_get()->server_port,
        cfg_get()->backup_ip, (unsigned)cfg_get()->backup_port,
        (unsigned)cfg_get()->report_moving_s,
        (unsigned)cfg_get()->report_stopped_s,
        (unsigned)cfg_get()->heartbeat_s,
        (unsigned)cfg_get()->heartbeat_s,
        (unsigned)jt808_is_online());
}

void log_platform_init(void) { s_last_ms = 0U; }
void log_platform_on_first_online(void) { s_last_ms = UINT32_MAX; }
void log_platform_on_blind_zone_uploaded(void) { s_last_ms = UINT32_MAX; }

void log_platform_process(void)
{
    size_t cap;
    uint8_t *buf;
    uint16_t len;
    uint32_t now = TICK_MS();
    if (work_mode_sleep_is_in_stop1() || !jt808_is_online() || ec800m_get_csq() < 6 ||
        fota_get_state() != FOTA_STATE_IDLE || fota_get_state() == FOTA_STATE_DOWNLOADING)
        return;
    if (s_last_ms != UINT32_MAX && (now - s_last_ms) < 600000UL) return;
    if (!service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_DIAGNOSTIC)) return;
    buf = service_workspace_buffer(&cap);
    len = build_log(buf, (uint16_t)cap);
    if (len > 0U && ec800m_udp_send_once(LOG_PLATFORM_HOST, LOG_PLATFORM_PORT, buf, len) == 0) {
        s_last_ms = now;
    }
    service_workspace_release(SERVICE_WORKSPACE_OWNER_DIAGNOSTIC);
}
