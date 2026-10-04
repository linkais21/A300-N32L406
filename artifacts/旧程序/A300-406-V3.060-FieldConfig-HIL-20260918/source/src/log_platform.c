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
#include "adc_monitor.h"
#include "n32l40x_rtc.h"
#include <math.h>
#include <stdio.h>
#include <string.h>

/* UINT32_MAX is the pending-event sentinel; keeps state to one word. */
static uint32_t s_last_ms;

static uint16_t build_log(uint8_t *buf, uint16_t cap)
{
    char imei[16];
    char iccid[24];
    int length;
    RTC_TimeType rtc;
    RTC_GetTime(RTC_FORMAT_BIN, &rtc);
    if (rtc.Hours > 23U || rtc.Minutes > 59U || rtc.Seconds > 59U)
        rtc.Hours = rtc.Minutes = rtc.Seconds = 0U;
    float volts = adc_monitor_valid() ? adc_get_car_voltage() : 0.0f;
    unsigned voltage_x10 = !isfinite(volts) || volts <= 0.0f ? 0U :
        volts >= 6553.5f ? 65535U : (unsigned)(volts * 10.0f + 0.5f);
    if (!buf || cap < 64U) return 0U;
    ec800m_get_imei(imei, sizeof imei);
    if (!imei[0]) return 0U;
    ec800m_get_iccid(iccid, sizeof iccid);
    size_t iccid_len = strlen(iccid);
    bool sim_ok = (iccid_len == 19U || iccid_len == 20U) &&
                  strspn(iccid, "0123456789ABCDEFabcdef") == iccid_len;
    if (!sim_ok) iccid[0] = '\0';
    /* 6F: SIM status, ICCID, IMSI, OTA ID. Unknown fields stay empty. */
    length = snprintf((char *)buf, cap,
        "<LOG*%s*U:%s,%u*R:%02u%02u%02u*C:%d*3G:%s*3I:%u*3L:00*3T:1*3W:%s:%u*3X:%s:%u*4C:%u*4F:1*62:%u,%u,%u,%u*6F:%u,%s,,*74:%u>",
        imei, cfg_get()->server_ip, (unsigned)cfg_get()->server_port,
        (unsigned)rtc.Hours, (unsigned)rtc.Minutes, (unsigned)rtc.Seconds,
        ec800m_get_csq(), FW_FULL_VERSION,
        gps_is_valid() ? 1U : 0U,
        cfg_get()->server_ip, (unsigned)cfg_get()->server_port,
        cfg_get()->backup_ip, (unsigned)cfg_get()->backup_port,
        voltage_x10,
        (unsigned)cfg_get()->report_moving_s,
        (unsigned)cfg_get()->report_stopped_s,
        (unsigned)cfg_get()->heartbeat_s,
        (unsigned)cfg_get()->heartbeat_s,
        sim_ok && ec800m_sim_ready() ? 0U : 1U, iccid,
        (unsigned)jt808_is_online());
    return length > 0 && length < cap ? (uint16_t)length : 0U;
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
