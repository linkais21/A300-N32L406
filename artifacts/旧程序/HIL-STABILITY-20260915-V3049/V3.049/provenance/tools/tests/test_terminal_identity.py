#!/usr/bin/env python3
"""Host behavior tests for bounded PID/IMEI terminal identity derivation."""

from __future__ import annotations

import os
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import release_guard  # noqa: E402

HARNESS = r'''
#include <stdint.h>
#include "config.h"
#include "terminal_identity.h"
#include "flash_config.h"
#include "jt808.h"
#include "blind_zone.h"
#include "jt808_params.h"
#include "jt808_terminal_info.h"
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

static device_config_t s_config;
static char s_imei[16];
static char s_iccid[22] = "89860412102500000001";
static unsigned s_raw_count;
static unsigned s_response_count;
static uint16_t s_raw_message;
static uint8_t s_raw_body[96];
static uint16_t s_raw_length;
static uint16_t s_response_sn;
static uint16_t s_response_id;
static uint8_t s_response_result;
static unsigned s_store_calls;
static bool s_store_ok = true;
static cfg_store_result_t s_pid_store_result = CFG_STORE_OK;
volatile uint32_t g_tick_ms;

device_config_t *cfg_get(void)
{
    return &s_config;
}

void ec800m_get_imei(char *buf, uint8_t size)
{
    size_t length = strlen(s_imei);
    if (buf == NULL || size == 0U) return;
    if (length >= size) length = (size_t)size - 1U;
    memcpy(buf, s_imei, length);
    buf[length] = '\0';
}

int jt808_send_raw(uint16_t message, uint16_t sn,
                   const uint8_t *body, uint16_t length)
{
    (void)sn;
    assert(length <= sizeof(s_raw_body));
    ++s_raw_count;
    s_raw_message = message;
    s_raw_length = length;
    memcpy(s_raw_body, body, length);
    return 0;
}

int jt808_send_general_resp(uint16_t sn, uint16_t message, uint8_t result)
{
    ++s_response_count;
    s_response_sn = sn;
    s_response_id = message;
    s_response_result = result;
    return 0;
}

int dbg_printf(const char *format, ...)
{
    (void)format;
    return 0;
}

void jt808_set_heartbeat_s(uint16_t seconds) { (void)seconds; }
void jt808_set_report_interval(uint16_t moving, uint16_t stopped)
{
    (void)moving;
    (void)stopped;
}

void ec800m_get_iccid(char *buf, uint8_t size)
{
    size_t length = strlen(s_iccid);
    if (buf == NULL || size == 0U) return;
    if (length >= size) length = (size_t)size - 1U;
    memcpy(buf, s_iccid, length);
    buf[length] = '\0';
}
void work_mode_config_changed(const device_config_t *config, uint32_t now_s)
{
    (void)config;
    (void)now_s;
}
void cfg_set_server(const char *ip, uint16_t port, bool backup)
{
    (void)ip;
    (void)port;
    (void)backup;
}
void cfg_save(void) {}
bool cfg_store_candidate(const device_config_t *candidate)
{
    ++s_store_calls;
    if (!s_store_ok) return false;
    s_config = *candidate;
    return true;
}
cfg_store_result_t cfg_set_pid_result(const char pid[CFG_PID_LEN])
{
    ++s_store_calls;
    if (s_pid_store_result != CFG_STORE_OK) return s_pid_store_result;
    memcpy(s_config.pid, pid, CFG_PID_LEN);
    return CFG_STORE_OK;
}

static void expect_derive(const char *pid, const char *imei, const char *expected)
{
    char out[8] = {'X','X','X','X','X','X','X','X'};
    assert(terminal_id_derive(pid, imei, out));
    assert(strcmp(out, expected) == 0);
    assert(out[7] == '\0');
}

static void expect_invalid(const char *pid, const char *imei)
{
    char out[8] = {'X','X','X','X','X','X','X','X'};
    assert(!terminal_id_derive(pid, imei, out));
    assert(out[0] == '\0');
}

static void set_identity(const char *pid, const char *imei)
{
    memset(&s_config, 0, sizeof(s_config));
    memset(s_imei, 0, sizeof(s_imei));
    if (pid != NULL) strncpy(s_config.pid, pid, sizeof(s_config.pid) - 1U);
    if (imei != NULL) strncpy(s_imei, imei, sizeof(s_imei) - 1U);
}

int main(void)
{
    char out[8] = {'X','X','X','X','X','X','X','X'};
    char pid[12];
    char phone[13];
    char terminal_id[8];
    uint8_t bcd[6];

    expect_derive("12345678901", "not-used", "5678901");
    expect_derive("", "123456789012345", "9012345");
    expect_invalid("", "1234567");
    expect_invalid("", "01234567");
    expect_invalid("", "12345678901234");
    expect_derive("00001234567", "any-imei", "1234567");

    expect_invalid("12345x78901", "123456789012345");
    expect_invalid("1234567890", "123456789012345");
    expect_invalid("123456789012", "123456789012345");
    expect_invalid("", "");
    expect_invalid("", "123456");
    expect_invalid("", "12345678901234x");
    expect_invalid("", "1234567890123456");
    expect_invalid(NULL, "123456789012345");
    expect_invalid("", NULL);
    assert(!terminal_id_derive("12345678901", "123456789012345", NULL));

    set_identity("", "123456789012345");
    s_store_calls = 0U; s_store_ok = true; s_pid_store_result = CFG_STORE_OK;
    assert(terminal_identity_sync_result(pid, phone, terminal_id, NULL) ==
           TERMINAL_IDENTITY_OK_DERIVED);
    assert(strcmp(pid, "56789012345") == 0);
    assert(strcmp(phone, "056789012345") == 0);
    assert(strcmp(terminal_id, "9012345") == 0);
    assert(strcmp(s_config.pid, "56789012345") == 0);
    assert(s_store_calls == 1U);
    assert(terminal_identity_encode_phone(pid, bcd));
    assert(memcmp(bcd, (uint8_t[]){0x05,0x67,0x89,0x01,0x23,0x45}, 6U) == 0);

    set_identity("12345678901", "987654321098765");
    s_store_calls = 0U;
    assert(terminal_identity_sync(pid, phone, terminal_id));
    assert(strcmp(pid, "12345678901") == 0 && s_store_calls == 0U);

    set_identity("", "123456789012345");
    s_store_calls = 0U; s_store_ok = false; s_pid_store_result = CFG_STORE_LOCK_FAILED;
    assert(terminal_identity_sync_result(pid, phone, terminal_id, NULL) ==
           TERMINAL_IDENTITY_FLASH_LOCK);
    assert(s_config.pid[0] == '\0' && s_store_calls == 1U);
    s_store_ok = true; s_pid_store_result = CFG_STORE_OK;
    set_identity("12345x78901", "123456789012345");
    assert(terminal_identity_sync_result(pid, phone, terminal_id, NULL) ==
           TERMINAL_IDENTITY_PID_FORMAT);
    set_identity("", "12345678901234x");
    assert(terminal_identity_sync_result(pid, phone, terminal_id, NULL) ==
           TERMINAL_IDENTITY_IMEI_FORMAT);

    set_identity("12345678901", "987654321098765");
    assert(terminal_identity_load(out));
    assert(strcmp(out, "5678901") == 0);
    assert(out[7] == '\0');

    set_identity("12345x78901", "123456789012345");
    memset(out, 'X', sizeof(out));
    assert(!terminal_identity_load(out));
    assert(out[0] == '\0');

    set_identity("", "123456789012345");
    assert(terminal_identity_load(out));
    assert(strcmp(out, "9012345") == 0);
    assert(out[7] == '\0');

    s_raw_count = s_response_count = 0U;
    set_identity("12345678901", "987654321098765");
    jt808_params_handle_info_query(0x1234U);
    assert(s_raw_count == 1U && s_response_count == 0U);
    assert(s_raw_message == 0x0107U && s_raw_length == 83U);
    assert(memcmp(s_raw_body, (uint8_t[]){0x00U, 0x0DU}, 2U) == 0);
    assert(memcmp(s_raw_body + 2U, "70110", 5U) == 0);
    assert(memcmp(s_raw_body + 7U, "T360-A300", 9U) == 0);
    assert(memcmp(s_raw_body + 16U, (uint8_t[11]){0}, 11U) == 0);
    assert(memcmp(s_raw_body + 27U, "5678901", 7U) == 0);
    assert(memcmp(s_raw_body + 34U,
                  (uint8_t[]){0x89U,0x86U,0x04U,0x12U,0x10U,
                              0x25U,0x00U,0x00U,0x00U,0x01U}, 10U) == 0);
    assert(s_raw_body[44U] == 0U);
    assert(s_raw_body[45U] == 35U);
    assert(memcmp(s_raw_body + 46U, FW_VERSION_STR, sizeof(FW_VERSION_STR) - 1U) == 0);
    assert(s_raw_body[81U] == 0x02U);
    assert(s_raw_body[82U] == 0x20U);

    strcpy(s_iccid, "8986041210250000001");
    jt808_params_handle_info_query(0x1234U);
    assert(memcmp(s_raw_body + 34U,
                  (uint8_t[]){0x08U,0x98U,0x60U,0x41U,0x21U,
                              0x02U,0x50U,0x00U,0x00U,0x01U}, 10U) == 0);

    /* The EC800M contract permits hexadecimal ICCID nibbles.  Preserve a
       modem-provided value exactly in the ten-byte terminal-attributes field. */
    strcpy(s_iccid, "898600000000D0000000");
    jt808_params_handle_info_query(0x1234U);
    assert(memcmp(s_raw_body + 34U,
                  (uint8_t[]){0x89U,0x86U,0x00U,0x00U,0x00U,
                              0x00U,0xD0U,0x00U,0x00U,0x00U}, 10U) == 0);
    strcpy(s_iccid, "898600000000d0000000");
    jt808_params_handle_info_query(0x1234U);
    assert(memcmp(s_raw_body + 34U,
                  (uint8_t[]){0x89U,0x86U,0x00U,0x00U,0x00U,
                              0x00U,0xD0U,0x00U,0x00U,0x00U}, 10U) == 0);

    strcpy(s_iccid, "898600000000G0000000");
    s_raw_count = s_response_count = 0U;
    jt808_params_handle_info_query(0x2345U);
    assert(s_raw_count == 0U && s_response_count == 1U);
    assert(s_response_result == 1U);
    strcpy(s_iccid, "89860412102500000001");

    {
        uint8_t encoded[JT808_TERMINAL_INFO_BODY_LENGTH];
        uint16_t encoded_length = 99U;
        assert(jt808_terminal_info_encode(NULL, sizeof(encoded), &encoded_length) ==
               JT808_TERMINAL_INFO_INVALID_ARGUMENT);
        assert(jt808_terminal_info_encode(encoded, sizeof(encoded), NULL) ==
               JT808_TERMINAL_INFO_INVALID_ARGUMENT);
        assert(jt808_terminal_info_encode(encoded, sizeof(encoded) - 1U,
                                          &encoded_length) ==
               JT808_TERMINAL_INFO_NO_SPACE);
        assert(encoded_length == 0U);
    }

    s_raw_count = s_response_count = 0U;
    set_identity("12345x78901", "123456789012345");
    jt808_params_handle_info_query(0x4567U);
    assert(s_raw_count == 0U && s_response_count == 1U);
    assert(s_response_sn == 0x4567U);
    assert(s_response_id == MSG_QUERY_TERMINAL_INFO);
    assert(s_response_result == 1U);
    return 0;
}
'''

JT808_HARNESS = r'''
#include "jt808.h"
#include "blind_zone.h"
#include "flash_config.h"
#include "gps.h"
#include "tcp_manager.h"
#include "work_mode.h"
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

volatile uint32_t g_tick_ms;
static device_config_t s_config;
static char s_imei[16];
static uint8_t s_sent[1024];
static uint16_t s_sent_length;
static unsigned s_send_count;
static unsigned s_imei_reads;
static unsigned s_identity_logs;
static unsigned s_device_logs;
static unsigned s_server_logs;
static char s_log[4096];
static size_t s_log_length;
static int s_send_result;
static bool s_online = true;
static cfg_store_result_t s_jt_pid_store_result = CFG_STORE_OK;

void blind_zone_replay_reset(void) {}
void blind_zone_replay_on_general_ack(uint16_t serial, uint16_t message, uint8_t result)
{ (void)serial; (void)message; (void)result; }
blind_zone_result_t blind_zone_append(const blind_zone_record_t *record)
{ (void)record; return BLIND_ZONE_BUSY; }

device_config_t *cfg_get(void) { return &s_config; }
void cfg_save(void) {}
bool cfg_store_candidate(const device_config_t *candidate)
{ s_config = *candidate; return true; }
cfg_store_result_t cfg_set_pid_result(const char pid[CFG_PID_LEN])
{
    if (s_jt_pid_store_result != CFG_STORE_OK) return s_jt_pid_store_result;
    memcpy(s_config.pid, pid, CFG_PID_LEN);
    return CFG_STORE_OK;
}
bool cfg_set_auth_code(uint8_t channel, const char *code)
{
    char *target = channel == 0U ? s_config.auth_code :
                   channel == 3U ? s_config.backup_auth_code : NULL;
    if (target == NULL || strlen(code) >= CFG_AUTH_LEN) return false;
    memset(target, 0, CFG_AUTH_LEN);
    memcpy(target, code, strlen(code));
    return true;
}
void ec800m_get_imei(char *buf, uint8_t size)
{
    size_t length = strlen(s_imei);
    ++s_imei_reads;
    if (length >= size) length = (size_t)size - 1U;
    memcpy(buf, s_imei, length);
    buf[length] = '\0';
}
void ec800m_get_iccid(char *buf, uint8_t size)
{
    const char *iccid = "89860412102500000001";
    size_t length = strlen(iccid);
    if (length >= size) length = (size_t)size - 1U;
    memcpy(buf, iccid, length);
    buf[length] = '\0';
}
bool ec800m_is_ready(void) { return true; }
void ec800m_register_recv(ec800m_recv_cb_t callback) { (void)callback; }
int ec800m_tcp_send(uint8_t channel, const uint8_t *data, uint16_t length)
{
    (void)channel;
    assert(length <= sizeof(s_sent));
    memcpy(s_sent, data, length);
    s_sent_length = length;
    ++s_send_count;
    return s_send_result;
}
bool ec800m_tcp_send_was_ambiguous(void) { return false; }
void ec800m_tcp_send_clear_ambiguous(void) {}
int ec800m_get_csq(void) { return 0; }
float adc_get_car_voltage(void) { return 0.0f; }
float adc_get_bat_voltage(void) { return 0.0f; }
bool tcp_manager_is_online(void) { return s_online; }
bool tcp_manager_ch_online(uint8_t channel) { return s_online && channel == EC800M_CH_MAIN; }
uint8_t tcp_manager_active_ch(void) { return EC800M_CH_MAIN; }
uint32_t tcp_manager_session_generation(uint8_t channel) { (void)channel; return 1U; }
tcp_state_t ec800m_tcp_state(uint8_t channel)
{ (void)channel; return s_online ? TCP_STATE_OPEN : TCP_STATE_CLOSED; }
const gps_data_t *gps_get_data(void) { static gps_data_t data; return &data; }
bool gps_get_last_trusted(gps_data_t *out) { (void)out; return false; }
bool i2c_accel_is_moving(void) { return false; }
bool hw_acc_is_on(void) { return false; }
work_mode_state_t work_mode_state(void) { return WORK_MODE_REALTIME; }
void log_platform_on_first_online(void) {}
int GPIO_ReadInputDataBit(void *port, unsigned pin) { (void)port; (void)pin; return 0; }
void relay_set(bool cut) { (void)cut; }
void geofence_handle_jt808(const uint8_t *body, uint16_t length, uint16_t sn)
{ (void)body; (void)length; (void)sn; }
void jt808_params_handle_set(const uint8_t *body, uint16_t length, uint16_t sn)
{ (void)body; (void)length; (void)sn; }
void jt808_params_handle_query(const uint8_t *body, uint16_t length, uint16_t sn)
{ (void)body; (void)length; (void)sn; }
void jt808_params_handle_info_query(uint16_t sn) { (void)sn; }
int dbg_printf(const char *format, ...)
{
    int written;
    va_list args;
    va_start(args, format);
    written = vsnprintf(s_log + s_log_length, sizeof(s_log) - s_log_length,
                        format, args);
    va_end(args);
    if (written > 0 && (size_t)written < sizeof(s_log) - s_log_length)
        s_log_length += (size_t)written;
    if (strncmp(format, "[808] identity invalid reason=", 30U) == 0)
        ++s_identity_logs;
    if (strncmp(format, "[DEVICE]", 8U) == 0) ++s_device_logs;
    if (strncmp(format, "[SERVER]", 8U) == 0) ++s_server_logs;
    return written;
}

static uint16_t unescape(uint8_t *out)
{
    uint16_t input, output = 0U;
    assert(s_sent_length >= 2U && s_sent[0] == 0x7eU && s_sent[s_sent_length - 1U] == 0x7eU);
    for (input = 1U; input + 1U < s_sent_length; ++input) {
        if (s_sent[input] == 0x7dU) {
            ++input;
            out[output++] = s_sent[input] == 0x01U ? 0x7dU : 0x7eU;
        } else {
            out[output++] = s_sent[input];
        }
    }
    return output;
}

static void reset_capture(void)
{
    s_sent_length = 0U;
    s_send_count = 0U;
    s_imei_reads = 0U;
    s_send_result = 0;
    s_online = true;
}

static void reset_logs(void)
{
    s_identity_logs = s_device_logs = s_server_logs = 0U;
    s_log_length = 0U;
    s_log[0] = '\0';
}

static uint16_t sent_serial(void)
{
    uint8_t frame[1024];
    uint16_t length = unescape(frame);
    assert(length >= 13U);
    return (uint16_t)(((uint16_t)frame[10] << 8) | frame[11]);
}

static void inject_register_response_result(uint16_t request_serial, uint8_t result)
{
    uint8_t frame[18] = {
        0x7eU, 0x81U, 0x00U, 0x00U, 0x03U,
        0U, 0U, 0U, 0U, 0U, 0U,
        0x12U, 0x34U,
        (uint8_t)(request_serial >> 8), (uint8_t)request_serial, result,
        0U, 0x7eU
    };
    uint8_t checksum_value = 0U;
    uint16_t i;
    for (i = 1U; i < 16U; ++i) checksum_value ^= frame[i];
    frame[16] = checksum_value;
    jt808_on_recv(EC800M_CH_MAIN, frame, sizeof(frame));
}

static void inject_register_response(uint16_t request_serial)
{
    uint8_t frame[19] = {
        0x7eU, 0x81U, 0x00U, 0x00U, 0x04U,
        0U, 0U, 0U, 0U, 0U, 0U,
        0x12U, 0x34U,
        (uint8_t)(request_serial >> 8), (uint8_t)request_serial, 0U, 'A',
        0U, 0x7eU
    };
    uint8_t checksum_value = 0U;
    uint16_t i;
    for (i = 1U; i < 17U; ++i) checksum_value ^= frame[i];
    frame[17] = checksum_value;
    jt808_on_recv(EC800M_CH_MAIN, frame, sizeof(frame));
}

int main(void)
{
    jt808_terminal_t terminal;
    uint8_t frame[1024];
    uint16_t length;
    memset(&terminal, 0, sizeof(terminal));
    memcpy(terminal.manufacturer_id, "CYHLL", 5U);
    strcpy(terminal.terminal_model, "A300_406");

    memset(&s_config, 0, sizeof(s_config));
    strcpy(s_config.pid, "12345678901");
    strcpy(s_config.server_ip, "119.147.205.85");
    s_config.server_port = 9999U;
    strcpy(s_imei, "987654321098765");
    jt808_init(&terminal);
    reset_logs();
    reset_capture();
    jt808_process();
    assert(s_send_count == 1U && s_imei_reads == 1U);
    assert(s_device_logs == 1U && s_server_logs == 1U);
    assert(strstr(s_log, "[DEVICE] IMEI=987654321098765 ICCID=89860412102500000001 DEVICE_ID=12345678901 JT808_TID=5678901 PID_SOURCE=CONFIG\r\n") != NULL);
    assert(strstr(s_log, "[SERVER] MAIN=119.147.205.85:9999 BACKUP=OFF\r\n") != NULL);
    jt808_process();
    assert(s_device_logs == 1U && s_server_logs == 1U);
    length = unescape(frame);
    assert(length > 49U && frame[0] == 0x01U && frame[1] == 0x00U);
    assert(memcmp(frame + 41U, "5678901", 7U) == 0);

    strcpy(terminal.auth_code, "AUTH");
    jt808_init(&terminal);
    reset_logs();
    reset_capture();
    jt808_process();
    length = unescape(frame);
    assert(s_send_count == 1U && s_imei_reads == 1U);
    assert(length > 16U && frame[0] == 0x01U && frame[1] == 0x02U);

    strcpy(s_config.pid, "00001234567");
    reset_capture();
    assert(jt808_send_register_to(EC800M_CH_MAIN) == 0);
    length = unescape(frame);
    assert(s_imei_reads == 0U && memcmp(frame + 41U, "1234567", 7U) == 0);

    strcpy(s_config.pid, "76543210987");
    jt808_request_reregister();
    reset_capture();
    jt808_process();
    length = unescape(frame);
    assert(s_send_count == 1U && frame[0] == 0x01U && frame[1] == 0x00U);
    assert(memcmp(frame + 41U, "3210987", 7U) == 0);

    /* A registration response from before a TCP disconnect is stale. */
    {
        uint16_t disconnected_serial = sent_serial();
        s_online = false;
        jt808_process();
        s_online = true;
        reset_capture();
        inject_register_response(disconnected_serial);
        assert(s_send_count == 0U);
        jt808_process();
        assert(s_send_count == 1U);
        length = unescape(frame);
        assert(frame[0] == 0x01U && frame[1] == 0x00U);
        assert(memcmp(frame + 41U, "3210987", 7U) == 0);
    }

    /* Registration rejection must not lose forced re-registration on reconnect. */
    {
        uint16_t rejected_serial = sent_serial();
        reset_capture();
        inject_register_response_result(rejected_serial, 1U);
        assert(s_send_count == 0U);
        s_online = false;
        jt808_process();
        s_online = true;
        reset_capture();
        jt808_process();
        assert(s_send_count == 1U);
        length = unescape(frame);
        assert(frame[0] == 0x01U && frame[1] == 0x00U);
        assert(memcmp(frame + 41U, "3210987", 7U) == 0);
    }

    /* A response for the old PID must not defeat a newly requested registration. */
    {
        uint16_t old_serial = sent_serial();
        strcpy(s_config.pid, "11111222222");
        jt808_request_reregister();
        reset_capture();
        jt808_process();
        assert(s_send_count == 1U);
        length = unescape(frame);
        assert(frame[0] == 0x01U && frame[1] == 0x00U);
        assert(memcmp(frame + 41U, "1222222", 7U) == 0);
        {
            uint16_t new_serial = sent_serial();
            reset_capture();
            inject_register_response(old_serial);
            assert(s_send_count == 0U);
            inject_register_response(new_serial);
            assert(s_send_count == 0U);
            jt808_process();
            assert(s_send_count == 1U);
            length = unescape(frame);
            assert(frame[0] == 0x01U && frame[1] == 0x02U);
        }
    }

    jt808_request_reregister();
    reset_capture();
    s_send_result = -1;
    g_tick_ms = 6000U; jt808_process();
    assert(s_send_count == 1U);
    s_send_result = 0;
    g_tick_ms = 6001U; jt808_process();
    assert(s_send_count == 1U);
    g_tick_ms = 10999U; jt808_process();
    assert(s_send_count == 1U);
    g_tick_ms = 11000U; jt808_process();
    assert(s_send_count == 2U);
    g_tick_ms = 11001U; jt808_process();
    assert(s_send_count == 2U);
    length = unescape(frame);
    assert(frame[0] == 0x01U && frame[1] == 0x00U);

    reset_capture();
    g_tick_ms = 10000U;
    jt808_request_reregister();
    jt808_process();
    assert(s_send_count == 1U);
    g_tick_ms = 14999U; jt808_process();
    assert(s_send_count == 1U);
    g_tick_ms = 15000U; jt808_process();
    assert(s_send_count == 2U);

    reset_capture();
    g_tick_ms = 20000U;
    jt808_request_reregister();
    jt808_process();
    assert(s_send_count == 1U);
    s_send_result = -1;
    g_tick_ms = 25000U; jt808_process();
    assert(s_send_count == 2U);
    s_send_result = 0;
    g_tick_ms = 29999U; jt808_process();
    assert(s_send_count == 2U);
    g_tick_ms = 30000U; jt808_process();
    assert(s_send_count == 3U);
    length = unescape(frame);
    assert(frame[0] == 0x01U && frame[1] == 0x00U);

    /* Identity invalidation during a registration retry uses the same limiter. */
    reset_capture();
    s_identity_logs = 0U;
    strcpy(s_config.pid, "12345678901");
    g_tick_ms = 40000U;
    jt808_request_reregister();
    jt808_process();
    assert(s_send_count == 1U);
    {
        uint16_t invalidated_serial = sent_serial();
    strcpy(s_config.pid, "12345x78901");
    g_tick_ms = 45000U; jt808_process();
        reset_capture();
        inject_register_response(invalidated_serial);
        assert(s_send_count == 0U);
    }
    g_tick_ms = 45001U; jt808_process();
    g_tick_ms = 50000U; jt808_process();
    assert(s_send_count == 0U && s_identity_logs == 1U);

    strcpy(s_config.pid, "12345x78901");
    jt808_init(&terminal);
    reset_capture();
    reset_logs();
    g_tick_ms = 100U; jt808_process();
    g_tick_ms = 200U; jt808_process();
    g_tick_ms = 5100U; jt808_process();
    assert(s_send_count == 0U && s_identity_logs == 2U);
    assert(strstr(s_log, "[808] identity invalid reason=PID_FORMAT\r\n") != NULL);

    memset(s_config.pid, 0, sizeof(s_config.pid));
    strcpy(s_config.backup_ip, "58.61.154.237");
    s_config.backup_port = 7018U;
    strcpy(s_imei, "123456789012345");
    s_jt_pid_store_result = CFG_STORE_OK;
    jt808_init(&terminal);
    reset_logs();
    reset_capture();
    g_tick_ms = 6000U; jt808_process();
    assert(s_device_logs == 1U && s_server_logs == 1U);
    assert(strstr(s_log, "DEVICE_ID=56789012345 JT808_TID=9012345 PID_SOURCE=IMEI") != NULL);
    assert(strstr(s_log, "BACKUP=58.61.154.237:7018\r\n") != NULL);
    return 0;
}
'''

DIGRAPH_MACRO_HARNESS = r'''
#include <stdbool.h>
#include <string.h>

static bool terminal_id_derive(const char *pid, const char *imei, char out[8])
{
    (void)pid;
    (void)imei;
    (void)out;
    return false;
}

%:define OUT terminal_id

static bool device_id(unsigned imei_len, char terminal_id[8])
{
    if (imei_len == 99U) return terminal_id_derive("", "", terminal_id);
    memset(OUT, 49, 7U);
    memset(OUT + 7, 0, 1U);
    return true;
}

int main(void)
{
    char terminal_id[8];
    return device_id(0U, terminal_id) && terminal_id[0] == '1' && terminal_id[7] == '\0'
        ? 0 : 1;
}
'''

EXTENDED_IDENTIFIER_HARNESS = r'''
#include <stdbool.h>
#include <string.h>

static bool terminal_id_derive(const char *pid, const char *imei, char out[8])
{
    (void)pid;
    (void)imei;
    (void)out;
    return false;
}

#define Ω terminal_id

static bool device_id(unsigned imei_len, char terminal_id[8])
{
    if (imei_len == 99U) return terminal_id_derive("", "", terminal_id);
    memset(Ω, 49, 7U);
    memset(Ω + 7, 0, 1U);
    return true;
}

int main(void)
{
    char terminal_id[8];
    return device_id(0U, terminal_id) && terminal_id[0] == '1' && terminal_id[7] == '\0'
        ? 0 : 1;
}
'''

TRIGRAPH_SPLICE_HARNESS = r'''
#include <stdbool.h>
#include <string.h>

static bool terminal_id_derive(const char *pid, const char *imei, char out[8])
{
    (void)pid;
    (void)imei;
    (void)out;
    return false;
}

static bool device_id(unsigned imei_len, char terminal_id[8])
{
    if (imei_len == 99U) return terminal_id_derive("", "", terminal_id);
??=??/
include "fixed_identity.inc"
}

int main(void)
{
    char terminal_id[8];
    return device_id(0U, terminal_id) && terminal_id[0] == '1' && terminal_id[7] == '\0'
        ? 0 : 1;
}
'''

QUOTED_COMMENT_HARNESS = r'''
#include <stdbool.h>
#include <string.h>

static bool terminal_id_derive(const char *pid, const char *imei, char out[8])
{
    (void)pid;
    (void)imei;
    (void)out;
    return false;
}

static const char *guard_open = "/*";
#define OUT terminal_id
static const char *guard_close = "*/";

static bool device_id(unsigned imei_len, char terminal_id[8])
{
    if (imei_len == 99U) return terminal_id_derive("", "", terminal_id);
    memset(OUT, 49, 7U);
    memset(OUT + 7, 0, 1U);
    return true;
}

int main(void)
{
    char terminal_id[8];
    return guard_open[0] == '/' && guard_close[0] == '*' &&
        device_id(0U, terminal_id) && terminal_id[0] == '1' && terminal_id[7] == '\0'
        ? 0 : 1;
}
'''


def compiler() -> str | None:
    found = shutil.which("gcc") or shutil.which("cc")
    if found:
        return found
    base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    matches = list(base.glob("BrechtSanders.WinLibs*/mingw64/bin/gcc.exe"))
    return str(matches[0]) if matches else None


def test_release_guard_behavior() -> None:
    fixed = 'strncpy(s_terminal.terminal_id, "T663B01", 7);\n'
    numeric = 'memcpy(terminal_id, "1234567", 7);\n'
    split = 'memcpy(terminal_id, "123" "4567", 7);\n'
    alpha_split = 'memcpy(terminal_id, "ABC" "1234", 7);\n'
    byte_array = "static const char terminal_id[8] = {'1','2','3','4','5','6','7',0};\n"
    hex_array = "static const char terminal_id[8] = {0x31,0x32,0x33,0x34,0x35,0x36,0x37,0};\n"
    suffixed_hex_array = (
        "static const char terminal_id[8] = "
        "{0x31U,0x32UL,0x33LU,0x34L,0x35uL,0x36lU,0x37LLU,0U};\n"
    )
    escaped_char_array = (
        "static const char terminal_id[8] = "
        "{'\\x31','\\062','\\x33','\\064','\\x35','\\066','\\x37','\\0'};\n"
    )
    wrapped_array = (
        "static const char terminal_id[8] = "
        "{((uint8_t)(0x31U)),(0x32UL),(unsigned char)0x33LU,(0x34L),"
        "(0x35uL),(0x36lU),(0x37LLU),(0U)};\n"
    )
    prefixed_char_array = (
        "static const int terminal_id[8] = "
        "{L'\\x31',u'\\062',U'\\x33',L'\\064',u'\\x35',U'\\066',L'\\x37',L'\\0'};\n"
    )
    info_query = 'memcpy(tid, "1234567", 7);\n'
    strcpy_form = 'strcpy(terminal_id, "1234567");\n'
    initializer = 'char terminal_id[8] = "1234567";\n'
    multiline = 'memcpy(terminal_id,\n "1234567",\n 7);\n'
    centralized = 'if (terminal_identity_load(terminal_id)) send(terminal_id);\n'
    assert release_guard.fixed_identity_findings(fixed)
    assert release_guard.fixed_identity_findings(numeric)
    assert release_guard.fixed_identity_findings(split)
    assert release_guard.fixed_identity_findings(alpha_split)
    assert release_guard.fixed_identity_findings(byte_array)
    assert release_guard.fixed_identity_findings(hex_array)
    assert release_guard.fixed_identity_findings(suffixed_hex_array)
    assert release_guard.fixed_identity_findings(escaped_char_array)
    assert release_guard.fixed_identity_findings(wrapped_array)
    assert release_guard.fixed_identity_findings(prefixed_char_array)
    assert release_guard.fixed_identity_findings(info_query)
    assert release_guard.fixed_identity_findings(strcpy_form)
    assert release_guard.fixed_identity_findings(initializer)
    assert release_guard.fixed_identity_findings(multiline)
    assert not release_guard.fixed_identity_findings(centralized)
    assert not release_guard.fixed_identity_findings('/* "1234567" */\n')

    target = release_guard.TARGET_VERSION
    assert release_guard.generated_version_is_target(
        '$IDENTITY = Get-Content release_identity.json | ConvertFrom-Json\n'
        '$FW_VERSION = $IDENTITY.firmware_version\n'
    )
    assert not release_guard.generated_version_is_target(
        '$FW_VERSION = "T663B_B409_${BUILD_DATE}_${BUILD_TIME}"\n'
    )
    assert release_guard.c_define_is_target(f'#define FW_VERSION_STR "{target}"\n', "FW_VERSION_STR")
    assert not release_guard.c_define_is_target('#define FW_VERSION_STR "WRONG"\n', "FW_VERSION_STR")

    with tempfile.TemporaryDirectory(prefix="identity_guard_") as directory:
        root = Path(directory)
        for relative in (
            "src/main.c", "src/jt808.c", "src/jt808_params.c", "src/terminal_identity.c",
            "src/jt808_terminal_info.c", "src/f39_reply.c",
            "include/config.h", "include/build_version.h", "include/f39_reply.h",
            "include/jt808.h", "include/jt808_terminal_info.h", "include/work_mode.h",
            "gen_version.ps1", "release_identity.json",
        ):
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, destination)
        build_version_path = root / "include/build_version.h"
        committed_build_version = (ROOT / "include/build_version.h").read_text(
            encoding="utf-8"
        )
        generated_build_version = (
            "/* Auto-generated build version - DO NOT EDIT */\n"
            "#ifndef BUILD_VERSION_H\n"
            "#define BUILD_VERSION_H\n\n"
            "#define FW_BUILD_NUMBER  \"20991231_235959\"\n"
            "#define FW_BUILD_DATE    \"Dec 31 2099 - 23:59:59\"\n"
            f"#define FW_FULL_VERSION  \"{target}\"\n"
            f"#define FW_VERSION_COUNTER  {release_guard.TARGET_VERSION_COUNTER}UL\n\n"
            "#endif /* BUILD_VERSION_H */\n"
        )

        for form_name, build_version in (
            ("committed", committed_build_version),
            ("generated", generated_build_version),
        ):
            build_version_path.write_text(build_version, encoding="utf-8")
            baseline_findings = release_guard.scan(root)
            assert not baseline_findings, (
                f"{form_name} build_version.h release tree must pass: "
                f"{baseline_findings!r}"
            )
            build_version_path.write_text(
                build_version.replace(target, "T360-A300_406_20260823000001,V3.000"),
                encoding="utf-8",
            )
            findings = release_guard.scan(root)
            assert any(item[2] == "<target-version>" for item in findings), form_name

        build_version_path.write_text(generated_build_version, encoding="utf-8")

        contract_path = root / "release_identity.json"
        contract_original = contract_path.read_text(encoding="utf-8")
        invalid_contract = json.loads(contract_original)
        invalid_contract["firmware_revision"] = (invalid_contract["firmware_revision"] + 1) % 1000
        contract_path.write_text(json.dumps(invalid_contract), encoding="utf-8")
        findings = release_guard.scan(root)
        assert any(item[2] == "<release-contract>" for item in findings)
        contract_path.write_text(contract_original, encoding="utf-8")

        mutations = {
            "src/main.c": '\nstrcpy(s_terminal.terminal_id, "1234567");\n',
            "src/jt808.c": '\nstatic const char fixed_id[] = "7654321";\n',
            "src/jt808_params.c": '\nmemcpy(tid,\n "9012345", 7);\n',
            "src/terminal_identity.c": '\nmemcpy(out, "3456789", 7);\n',
            "src/f39_reply.c": '\nmemcpy(terminal_id, "123" "4567", 7);\n',
        }
        for relative, mutation in mutations.items():
            destination = root / relative
            original = destination.read_text(encoding="utf-8")
            destination.write_text(original + mutation, encoding="utf-8")
            findings = release_guard.scan(root)
            assert any(item[2] == "<fixed-terminal-id>" for item in findings), relative
            destination.write_text(original, encoding="utf-8")

        destination = root / "src/f39_reply.c"
        original = destination.read_text(encoding="utf-8")
        destination.write_text(
            original + "\nstatic const char fixed_bytes[8] = {'1','2','3','4','5','6','7',0};\n",
            encoding="utf-8",
        )
        findings = release_guard.scan(root)
        assert any(item[2] == "<fixed-terminal-id>" for item in findings)
        destination.write_text(original, encoding="utf-8")

        destination.write_text(
            original + ("\nstatic const char fixed_wrapped[8] = "
                        "{((uint8_t)(0x31U)),(0x32UL),(unsigned char)0x33LU,(0x34L),"
                        "(0x35uL),(0x36lU),(0x37LLU),(0U)};\n"),
            encoding="utf-8",
        )
        findings = release_guard.scan(root)
        assert any(item[2] == "<fixed-terminal-id>" for item in findings)
        destination.write_text(original, encoding="utf-8")

        destination.write_text(
            original + ("\nstatic const char fixed_suffixed[8] = "
                        "{0x31U,0x32UL,0x33LU,0x34L,0x35uL,0x36lU,0x37LLU,0U};\n"),
            encoding="utf-8",
        )
        findings = release_guard.scan(root)
        assert any(item[2] == "<fixed-terminal-id>" for item in findings)
        destination.write_text(original, encoding="utf-8")

        destination.write_text(
            original + ("\nstatic const char fixed_escaped[8] = "
                        "{'\\x31','\\062','\\x33','\\064','\\x35','\\066','\\x37','\\0'};\n"),
            encoding="utf-8",
        )
        findings = release_guard.scan(root)
        assert any(item[2] == "<fixed-terminal-id>" for item in findings)
        destination.write_text(original, encoding="utf-8")

        destination.write_text(
            original + "\nstatic const char fixed_hex[8] = {0x31,0x32,0x33,0x34,0x35,0x36,0x37,0};\n",
            encoding="utf-8",
        )
        findings = release_guard.scan(root)
        assert any(item[2] == "<fixed-terminal-id>" for item in findings)
        destination.write_text(original, encoding="utf-8")

        destination.write_text(
            original.replace("terminal_id_derive", "legacy_identity_derive"), encoding="utf-8"
        )
        findings = release_guard.scan(root)
        assert any(item[2] == "<identity-service>" for item in findings)
        destination.write_text(original, encoding="utf-8")

        argument_macro_decoy = (
            "if (p->imei_len == 99U) return terminal_id_derive(c->pid, imei, terminal_id); "
            "memset(OUT, 49, 7U); memset(OUT + 7, 0, 1U); return true;"
        )
        destination.write_text(
            "#define OUT terminal_id\n" + original.replace(
                "return terminal_id_derive(c->pid, imei, terminal_id);", argument_macro_decoy
            ),
            encoding="utf-8",
        )
        findings = release_guard.scan(root)
        assert any(item[2] == "<identity-service>" for item in findings)
        destination.write_text(original, encoding="utf-8")

        canonical = release_guard.c_function_body(original, "device_id")
        assert canonical is not None
        assert release_guard.canonical_identity_consumer(
            original, "src/f39_reply.c", "device_id", canonical
        ) is None

        destination.write_text(
            original.replace(
                "return terminal_id_derive(c->pid, imei, terminal_id);",
                "(void)0; return terminal_id_derive(c->pid, imei, terminal_id);",
            ),
            encoding="utf-8",
        )
        findings = release_guard.scan(root)
        assert any(item[2] == "<identity-service>" for item in findings)
        destination.write_text(original, encoding="utf-8")

        token_paste_decoy = (
            "if (p->imei_len == 99U) return terminal_id_derive(c->pid, imei, terminal_id); "
            "memset(CAT(terminal,_id), 49, 7U); CAT(terminal,_id)[7] = 0; return true;"
        )
        destination.write_text(
            "#define CAT_(a,b) a##b\n#define CAT(a,b) CAT_(a,b)\n" + original.replace(
                "return terminal_id_derive(c->pid, imei, terminal_id);", token_paste_decoy
            ),
            encoding="utf-8",
        )
        findings = release_guard.scan(root)
        assert any(item[2] == "<identity-service>" for item in findings)
        destination.write_text(original, encoding="utf-8")

        config_path = root / "include/config.h"
        config_original = config_path.read_text(encoding="utf-8")
        config_path.write_text(config_original + "\n/* manual review */\n", encoding="utf-8")
        findings = release_guard.scan(root)
        assert any(item[2] == "<identity-service>" for item in findings)
        config_path.write_text(config_original, encoding="utf-8")

        config_path.write_text(
            config_original + "\n#define CAT_(a,b) a##b\n#define CAT(a,b) CAT_(a,b)\n",
            encoding="utf-8",
        )
        destination.write_text(
            original.replace(
                "return terminal_id_derive(c->pid, imei, terminal_id);", token_paste_decoy
            ),
            encoding="utf-8",
        )
        findings = release_guard.scan(root)
        assert any(item[2] == "<identity-service>" for item in findings)
        destination.write_text(original, encoding="utf-8")
        config_path.write_text(config_original, encoding="utf-8")

        config_path.write_text(
            config_original + ('\nstatic const char *guard_open = "/*";\n'
                               '#define OUT terminal_id\n'
                               'static const char *guard_close = "*/";\n'),
            encoding="utf-8",
        )
        destination.write_text(
            original.replace(
                "return terminal_id_derive(c->pid, imei, terminal_id);", argument_macro_decoy
            ),
            encoding="utf-8",
        )
        findings = release_guard.scan(root)
        assert any(item[2] == "<identity-service>" for item in findings)
        destination.write_text(original, encoding="utf-8")
        config_path.write_text(config_original, encoding="utf-8")

        config_path.write_text(
            config_original + ("\n#undef FW_MODEL_STR\n"
                               "#define FW_MODEL_STR "
                               "(memset(tid,49,7U),tid[7]=0,\"A300_406\")\n"),
            encoding="utf-8",
        )
        findings = release_guard.scan(root)
        assert any(item[2] == "<identity-service>" for item in findings)
        config_path.write_text(config_original, encoding="utf-8")

        include_fragment = root / "include/fixed_identity.inc"
        include_fragment.write_text(
            "memset(terminal_id, 49, 7U); terminal_id[7] = 0; return true;\n",
            encoding="utf-8",
        )
        include_decoy = (
            "if (p->imei_len == 99U) return terminal_id_derive(c->pid, imei, terminal_id); "
            "#include \"fixed_identity.inc\""
        )
        destination.write_text(
            original.replace(
                "return terminal_id_derive(c->pid, imei, terminal_id);", include_decoy
            ),
            encoding="utf-8",
        )
        findings = release_guard.scan(root)
        assert any(item[2] == "<identity-service>" for item in findings)
        destination.write_text(original, encoding="utf-8")
        include_fragment.unlink()

        include_fragment.write_text(
            "memset(terminal_id, 49, 7U); terminal_id[7] = 0; return true;\n",
            encoding="utf-8",
        )
        spliced_include_decoy = (
            "if (p->imei_len == 99U) return terminal_id_derive(c->pid, imei, terminal_id); "
            "#\\\ninclude \"fixed_identity.inc\""
        )
        destination.write_text(
            original.replace(
                "return terminal_id_derive(c->pid, imei, terminal_id);", spliced_include_decoy
            ),
            encoding="utf-8",
        )
        findings = release_guard.scan(root)
        assert any(item[2] == "<identity-service>" for item in findings)
        destination.write_text(original, encoding="utf-8")
        include_fragment.unlink()

        include_fragment.write_text(
            "memset(terminal_id, 49, 7U); terminal_id[7] = 0; return true;\n",
            encoding="utf-8",
        )
        digraph_include_decoy = (
            "if (p->imei_len == 99U) return terminal_id_derive(c->pid, imei, terminal_id); "
            "%:include \"fixed_identity.inc\""
        )
        destination.write_text(
            original.replace(
                "return terminal_id_derive(c->pid, imei, terminal_id);", digraph_include_decoy
            ),
            encoding="utf-8",
        )
        findings = release_guard.scan(root)
        assert any(item[2] == "<identity-service>" for item in findings)
        destination.write_text(original, encoding="utf-8")
        include_fragment.unlink()

        include_fragment.write_text(
            "memset(terminal_id, 49, 7U); terminal_id[7] = 0; return true;\n",
            encoding="utf-8",
        )
        trigraph_splice_decoy = (
            "if (p->imei_len == 99U) return terminal_id_derive(c->pid, imei, terminal_id); "
            "??=??/\ninclude \"fixed_identity.inc\""
        )
        destination.write_text(
            original.replace(
                "return terminal_id_derive(c->pid, imei, terminal_id);",
                trigraph_splice_decoy,
            ),
            encoding="utf-8",
        )
        findings = release_guard.scan(root)
        assert any(item[2] == "<identity-service>" for item in findings)
        destination.write_text(original, encoding="utf-8")
        include_fragment.unlink()

        config_path.write_text(
            config_original + "\n#define OUT terminal_id\n", encoding="utf-8"
        )
        destination.write_text(
            original.replace(
                "return terminal_id_derive(c->pid, imei, terminal_id);", argument_macro_decoy
            ),
            encoding="utf-8",
        )
        findings = release_guard.scan(root)
        assert any(item[2] == "<identity-service>" for item in findings)
        destination.write_text(original, encoding="utf-8")
        config_path.write_text(config_original, encoding="utf-8")

        config_path.write_text(
            config_original + "\n%:define OUT terminal_id\n", encoding="utf-8"
        )
        destination.write_text(
            original.replace(
                "return terminal_id_derive(c->pid, imei, terminal_id);", argument_macro_decoy
            ),
            encoding="utf-8",
        )
        findings = release_guard.scan(root)
        assert any(item[2] == "<identity-service>" for item in findings)
        destination.write_text(original, encoding="utf-8")
        config_path.write_text(config_original, encoding="utf-8")

        config_path.write_text(
            config_original + "\n#define Ω terminal_id\n", encoding="utf-8"
        )
        destination.write_text(
            original.replace(
                "return terminal_id_derive(c->pid, imei, terminal_id);",
                argument_macro_decoy.replace("OUT", "Ω"),
            ),
            encoding="utf-8",
        )
        findings = release_guard.scan(root)
        assert any(item[2] == "<identity-service>" for item in findings)
        destination.write_text(original, encoding="utf-8")
        config_path.write_text(config_original, encoding="utf-8")

        macro_decoy = (
            "memset(OUT, '1', 7U); OUT[7] = '\\0'; return true; "
            "if (p->imei_len == 0U) return terminal_id_derive(c->pid, imei, terminal_id);"
        )
        destination.write_text(
            "#define OUT terminal_id\n" + original.replace(
                "return terminal_id_derive(c->pid, imei, terminal_id);", macro_decoy
            ),
            encoding="utf-8",
        )
        findings = release_guard.scan(root)
        assert any(item[2] == "<identity-service>" for item in findings)
        destination.write_text(original, encoding="utf-8")

        for alias_expression in ("(terminal_id + 0)", "(&terminal_id[0])"):
            destination.write_text(
                f"#define OUT {alias_expression}\n" + original.replace(
                    "return terminal_id_derive(c->pid, imei, terminal_id);", macro_decoy
                ),
                encoding="utf-8",
            )
            findings = release_guard.scan(root)
            assert any(item[2] == "<identity-service>" for item in findings)
            destination.write_text(original, encoding="utf-8")

        function_macro_decoy = (
            "memset(OUT(), '1', 7U); OUT()[7] = '\\0'; return true; "
            "if (p->imei_len == 0U) return terminal_id_derive(c->pid, imei, terminal_id);"
        )
        destination.write_text(
            "#define OUT() terminal_id\n" + original.replace(
                "return terminal_id_derive(c->pid, imei, terminal_id);", function_macro_decoy
            ),
            encoding="utf-8",
        )
        findings = release_guard.scan(root)
        assert any(item[2] == "<identity-service>" for item in findings)
        destination.write_text(original, encoding="utf-8")

        destination.write_text(
            "#define OUT (terminal_id)\n" + original.replace(
                "return terminal_id_derive(c->pid, imei, terminal_id);", macro_decoy
            ),
            encoding="utf-8",
        )
        findings = release_guard.scan(root)
        assert any(item[2] == "<identity-service>" for item in findings)
        destination.write_text(original, encoding="utf-8")

        decoy = (
            "memset(terminal_id, '1', 7U); terminal_id[7] = '\\0'; return true; "
            "if (p->imei_len == 0U) return terminal_id_derive(c->pid, imei, terminal_id);"
        )
        destination.write_text(
            original.replace(
                "return terminal_id_derive(c->pid, imei, terminal_id);", decoy
            ),
            encoding="utf-8",
        )
        findings = release_guard.scan(root)
        assert any(item[2] == "<identity-service>" for item in findings)
        destination.write_text(original, encoding="utf-8")

        destination.write_text(
            original.replace(
                "return terminal_id_derive(c->pid, imei, terminal_id);", "return false;"
            ) + ("\nstatic bool dead_identity_call(const device_config_t *c, const char *imei, "
                 "char terminal_id[8]) { return terminal_id_derive(c->pid, imei, terminal_id); }\n"),
            encoding="utf-8",
        )
        findings = release_guard.scan(root)
        assert any(item[2] == "<identity-service>" for item in findings)
        destination.write_text(original, encoding="utf-8")

        (root / "include/config.h").write_text('#define FW_VERSION_STR "WRONG"\n', encoding="ascii")
        assert release_guard.scan(root)
        shutil.copyfile(ROOT / "include/config.h", root / "include/config.h")
        (root / "include/build_version.h").write_text('#define FW_FULL_VERSION "WRONG"\n', encoding="ascii")
        assert release_guard.scan(root)


def main() -> int:
    cc = compiler()
    if cc is None:
        if os.environ.get("REQUIRE_GCC") == "1":
            print("test_terminal_identity: FAIL (no C compiler available)")
            return 1
        print("test_terminal_identity: SKIP (no C compiler available)")
        return 0

    with tempfile.TemporaryDirectory(prefix="terminal_identity_") as directory:
        temp = Path(directory)
        harness = temp / "terminal_identity_harness.c"
        binary = temp / "terminal_identity_harness.exe"
        harness.write_text(HARNESS, encoding="ascii")
        (temp / "n32l40x.h").write_text(
            "#ifndef N32L40X_H\n#define N32L40X_H\n"
            "#define GPIOA ((void *)0)\n#define GPIO_PIN_3 3U\n#define GPIO_PIN_12 12U\n"
            "#define Bit_RESET 0\n"
            "int GPIO_ReadInputDataBit(void *, unsigned);\n#endif\n", encoding="ascii"
        )
        command = [
            cc, "-std=c99", "-Wall", "-Wextra", "-Werror", "-ffunction-sections",
            "-I", str(temp), "-I", str(ROOT / "include"), str(harness),
            str(ROOT / "src" / "terminal_identity.c"), "-o", str(binary),
            str(ROOT / "src" / "jt808_params.c"),
            str(ROOT / "src" / "jt808_terminal_info.c"), "-Wl,--gc-sections",
        ]
        compiled = subprocess.run(command, text=True, capture_output=True)
        if compiled.returncode != 0:
            print(compiled.stdout, end="")
            print(compiled.stderr, end="")
            print("test_terminal_identity: FAIL (C harness did not compile)")
            return 1
        executed = subprocess.run([str(binary)], text=True, capture_output=True)
        if executed.returncode != 0:
            print(executed.stdout, end="")
            print(executed.stderr, end="")
            print("test_terminal_identity: FAIL (C harness assertion)")
            return 1

        jt808_harness = temp / "jt808_identity_harness.c"
        jt808_binary = temp / "jt808_identity_harness.exe"
        jt808_harness.write_text(JT808_HARNESS, encoding="ascii")
        command = [
            cc, "-std=c99", "-Wall", "-Wextra", "-Werror",
            "-I", str(temp), "-I", str(ROOT / "include"), str(jt808_harness),
            str(ROOT / "src" / "terminal_identity.c"),
            str(ROOT / "src" / "jt808.c"), str(ROOT / "src" / "jt808_session.c"),
            str(ROOT / "src" / "jt808_terminal_info.c"),
            "-lm", "-o", str(jt808_binary),
        ]
        compiled = subprocess.run(command, text=True, capture_output=True)
        if compiled.returncode != 0:
            print(compiled.stdout, end="")
            print(compiled.stderr, end="")
            print("test_terminal_identity: FAIL (JT808 harness did not compile)")
            return 1
        executed = subprocess.run([str(jt808_binary)], text=True, capture_output=True)
        if executed.returncode != 0:
            print(executed.stdout, end="")
            print(executed.stderr, end="")
            print("test_terminal_identity: FAIL (JT808 harness assertion)")
            return 1

        digraph_harness = temp / "digraph_macro_harness.c"
        digraph_binary = temp / "digraph_macro_harness.exe"
        digraph_harness.write_text(DIGRAPH_MACRO_HARNESS, encoding="ascii")
        compiled = subprocess.run(
            [cc, "-std=c99", "-Wall", "-Wextra", "-Werror", str(digraph_harness),
             "-o", str(digraph_binary)],
            text=True,
            capture_output=True,
        )
        if compiled.returncode != 0:
            print(compiled.stdout, end="")
            print(compiled.stderr, end="")
            print("test_terminal_identity: FAIL (%:define mutation did not compile as C99)")
            return 1
        executed = subprocess.run([str(digraph_binary)], text=True, capture_output=True)
        if executed.returncode != 0:
            print(executed.stdout, end="")
            print(executed.stderr, end="")
            print("test_terminal_identity: FAIL (%:define mutation did not execute)")
            return 1

        extended_harness = temp / "extended_identifier_harness.c"
        extended_binary = temp / "extended_identifier_harness.exe"
        extended_harness.write_text(EXTENDED_IDENTIFIER_HARNESS, encoding="utf-8")
        compiled = subprocess.run(
            [cc, "-std=c99", "-Wall", "-Wextra", "-Werror", "-finput-charset=UTF-8",
             str(extended_harness), "-o", str(extended_binary)],
            text=True,
            capture_output=True,
        )
        if compiled.returncode != 0:
            print(compiled.stdout, end="")
            print(compiled.stderr, end="")
            print("test_terminal_identity: FAIL (extended macro mutation did not compile as C99)")
            return 1
        executed = subprocess.run([str(extended_binary)], text=True, capture_output=True)
        if executed.returncode != 0:
            print(executed.stdout, end="")
            print(executed.stderr, end="")
            print("test_terminal_identity: FAIL (extended macro mutation did not execute)")
            return 1

        trigraph_harness = temp / "trigraph_splice_harness.c"
        trigraph_binary = temp / "trigraph_splice_harness.exe"
        trigraph_harness.write_text(TRIGRAPH_SPLICE_HARNESS, encoding="ascii")
        (temp / "fixed_identity.inc").write_text(
            "memset(terminal_id, 49, 7U); terminal_id[7] = 0; return true;\n",
            encoding="ascii",
        )
        compiled = subprocess.run(
            [cc, "-std=c99", "-trigraphs", "-Wno-trigraphs", "-Wall", "-Wextra",
             "-Werror", str(trigraph_harness), "-o", str(trigraph_binary)],
            text=True,
            capture_output=True,
        )
        if compiled.returncode != 0:
            print(compiled.stdout, end="")
            print(compiled.stderr, end="")
            print("test_terminal_identity: FAIL (trigraph-splice mutation did not compile)")
            return 1
        executed = subprocess.run([str(trigraph_binary)], text=True, capture_output=True)
        if executed.returncode != 0:
            print(executed.stdout, end="")
            print(executed.stderr, end="")
            print("test_terminal_identity: FAIL (trigraph-splice mutation did not execute)")
            return 1

        quoted_comment_harness = temp / "quoted_comment_harness.c"
        quoted_comment_binary = temp / "quoted_comment_harness.exe"
        quoted_comment_harness.write_text(QUOTED_COMMENT_HARNESS, encoding="ascii")
        compiled = subprocess.run(
            [cc, "-std=c99", "-Wall", "-Wextra", "-Werror", str(quoted_comment_harness),
             "-o", str(quoted_comment_binary)],
            text=True,
            capture_output=True,
        )
        if compiled.returncode != 0:
            print(compiled.stdout, end="")
            print(compiled.stderr, end="")
            print("test_terminal_identity: FAIL (quoted-comment mutation did not compile)")
            return 1
        executed = subprocess.run([str(quoted_comment_binary)], text=True, capture_output=True)
        if executed.returncode != 0:
            print(executed.stdout, end="")
            print(executed.stderr, end="")
            print("test_terminal_identity: FAIL (quoted-comment mutation did not execute)")
            return 1

    print("test_terminal_identity: C99 -Wall -Wextra -Werror PASS")
    test_release_guard_behavior()
    print("test_terminal_identity: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
