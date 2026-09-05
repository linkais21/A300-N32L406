#!/usr/bin/env python3
"""Host behavior tests for acknowledged JT808 blind-zone replay."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def compiler() -> str:
    cc = os.environ.get("CC") or shutil.which("gcc") or shutil.which("clang")
    if not cc:
        base = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Packages"
        matches = list(base.glob("BrechtSanders.WinLibs*/mingw64/bin/gcc.exe"))
        if matches:
            cc = str(matches[0])
    if not cc:
        raise RuntimeError("a host C compiler is required")
    return cc


HARNESS = r'''
#include "blind_zone.h"
#include "blind_zone_replay.h"
#include "ec800m.h"
#include "flash_config.h"
#include "gps.h"
#include "jt808.h"
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

volatile uint32_t g_tick_ms;
static bool s_tcp_online = true;
static bool s_main_online = true;
static bool s_backup_online;
static uint32_t s_session_generation = 1U;
static int s_send_result;
static uint8_t s_sent[1024];
static uint16_t s_sent_length;
static unsigned s_send_count;
static uint8_t s_last_send_channel;
static unsigned s_param_set_count;
static unsigned s_geofence_count;
static unsigned s_relay_count;
static blind_zone_record_t s_queue[32];
static uint8_t s_queue_count;
static uint32_t s_queue_sequence = 1U;
static unsigned s_append_count;
static blind_zone_result_t s_append_script[4];
static uint8_t s_append_script_count;
static uint8_t s_append_script_index;
static bool s_append_event_pending;
static blind_zone_record_t s_append_pending_record;
static unsigned s_consume_count;
static bool s_consume_pending_once;
static bool s_consume_stale_once;
static uint8_t s_last_consumed;
static uint32_t s_last_consumed_sequence;
static gps_data_t s_gps;
static device_config_t s_config;

device_config_t *cfg_get(void) { return &s_config; }
void cfg_save(void) {}
bool cfg_store_candidate(const device_config_t *candidate)
{ s_config = *candidate; return true; }
cfg_store_result_t cfg_set_pid_result(const char pid[CFG_PID_LEN])
{ memcpy(s_config.pid, pid, CFG_PID_LEN); return CFG_STORE_OK; }
bool cfg_set_auth_code(uint8_t channel, const char *code)
{
    char *target = channel == EC800M_CH_MAIN ? s_config.auth_code :
                   channel == EC800M_CH_BACKUP ? s_config.backup_auth_code : NULL;
    if (target == NULL || strlen(code) >= CFG_AUTH_LEN) return false;
    memset(target, 0, CFG_AUTH_LEN); memcpy(target, code, strlen(code)); return true;
}
void ec800m_get_imei(char *buf, uint8_t size)
{
    const char *imei = "123456789012345";
    size_t n = strlen(imei);
    if (n >= size) n = size - 1U;
    memcpy(buf, imei, n); buf[n] = '\0';
}
void ec800m_get_iccid(char *buf, uint8_t size)
{
    const char *iccid = "89860412102500000001";
    size_t n = strlen(iccid);
    if (n >= size) n = size - 1U;
    memcpy(buf, iccid, n); buf[n] = '\0';
}
bool ec800m_is_ready(void) { return true; }
void ec800m_register_recv(ec800m_recv_cb_t cb) { (void)cb; }
int ec800m_tcp_send(uint8_t ch, const uint8_t *data, uint16_t length)
{
    s_last_send_channel = ch;
    assert(length <= sizeof(s_sent));
    memcpy(s_sent, data, length);
    s_sent_length = length;
    ++s_send_count;
    return s_send_result;
}
bool ec800m_tcp_send_was_ambiguous(void) { return false; }
void ec800m_tcp_send_clear_ambiguous(void) {}
bool hw_acc_is_on(void) { return false; }
bool gps_get_last_trusted(gps_data_t *out) { (void)out; return false; }
void log_platform_on_first_online(void) {}
void log_platform_on_blind_zone_uploaded(void) {}
int ec800m_get_csq(void) { return 19; }
float adc_get_car_voltage(void) { return 12.6f; }
float adc_get_bat_voltage(void) { return 4.0f; }
bool tcp_manager_is_online(void) { return s_tcp_online; }
bool tcp_manager_ch_online(uint8_t ch)
{ return s_tcp_online && ((ch == EC800M_CH_MAIN && s_main_online) ||
                          (ch == EC800M_CH_BACKUP && s_backup_online)); }
uint8_t tcp_manager_active_ch(void)
{ return s_main_online ? EC800M_CH_MAIN : EC800M_CH_BACKUP; }
uint32_t tcp_manager_session_generation(uint8_t ch)
{ return ch <= EC800M_CH_BACKUP ? s_session_generation : 0U; }
tcp_state_t ec800m_tcp_state(uint8_t ch)
{ (void)ch; return s_tcp_online ? TCP_STATE_OPEN : TCP_STATE_CLOSED; }
const gps_data_t *gps_get_data(void) { return &s_gps; }
bool i2c_accel_is_moving(void) { return false; }
int GPIO_ReadInputDataBit(void *port, unsigned pin)
{ (void)port; (void)pin; return 1; }
void relay_set(bool cut) { (void)cut; ++s_relay_count; }
void geofence_handle_jt808(const uint8_t *body, uint16_t length, uint16_t sn)
{ (void)body; (void)length; (void)sn; ++s_geofence_count; }
void jt808_params_handle_set(const uint8_t *body, uint16_t length, uint16_t sn)
{ (void)body; (void)length; (void)sn; ++s_param_set_count; }
void jt808_params_handle_query(const uint8_t *body, uint16_t length, uint16_t sn)
{ (void)body; (void)length; (void)sn; }
void jt808_params_handle_info_query(uint16_t sn) { (void)sn; }
int dbg_printf(const char *format, ...) { (void)format; return 0; }

bool blind_zone_init(void) { return true; }
void blind_zone_recovery_process(void) {}
bool blind_zone_ready(void) { return true; }
blind_zone_result_t blind_zone_append(const blind_zone_record_t *record)
{
    blind_zone_result_t result = BLIND_ZONE_OK;
    assert(record != NULL && s_queue_count < 32U);
    ++s_append_count;
    if (s_append_event_pending)
        assert(memcmp(record, &s_append_pending_record, sizeof(*record)) == 0);
    if (s_append_script_index < s_append_script_count)
        result = s_append_script[s_append_script_index++];
    if (result == BLIND_ZONE_PENDING) {
        if (!s_append_event_pending) s_append_pending_record = *record;
        s_append_event_pending = true;
        return result;
    }
    if (result != BLIND_ZONE_OK) return result;
    s_queue[s_queue_count++] = *record;
    s_append_event_pending = false;
    return result;
}
uint8_t blind_zone_peek(blind_zone_record_t *records, uint8_t capacity,
                        uint32_t *first_sequence)
{
    uint8_t count = capacity < s_queue_count ? capacity : s_queue_count;
    if (count == 0U) return 0U;
    memcpy(records, s_queue, count * sizeof(*records));
    *first_sequence = s_queue_sequence;
    return count;
}
blind_zone_result_t blind_zone_consume(uint32_t sequence, uint8_t count)
{
    assert(sequence == s_queue_sequence && count <= s_queue_count);
    ++s_consume_count;
    s_last_consumed = count;
    s_last_consumed_sequence = sequence;
    if (s_consume_pending_once) {
        s_consume_pending_once = false;
        return BLIND_ZONE_PENDING;
    }
    if (s_consume_stale_once) {
        s_consume_stale_once = false;
        return BLIND_ZONE_STALE;
    }
    memmove(s_queue, s_queue + count,
            (s_queue_count - count) * sizeof(s_queue[0]));
    s_queue_count -= count;
    s_queue_sequence += count;
    return BLIND_ZONE_OK;
}

static uint16_t unescape(uint8_t *frame)
{
    uint16_t i, length = 0U;
    assert(s_sent_length >= 2U && s_sent[0] == 0x7eU &&
           s_sent[s_sent_length - 1U] == 0x7eU);
    for (i = 1U; i + 1U < s_sent_length; ++i) {
        if (s_sent[i] == 0x7dU) {
            ++i;
            frame[length++] = s_sent[i] == 1U ? 0x7dU : 0x7eU;
        } else frame[length++] = s_sent[i];
    }
    return length;
}

static uint16_t sent_serial(void)
{
    uint8_t frame[1024];
    assert(unescape(frame) >= 13U);
    return (uint16_t)(((uint16_t)frame[10] << 8) | frame[11]);
}

static void inject_ack_ch(uint8_t channel, uint16_t request_serial,
                          uint16_t request_message, uint8_t result,
                          uint16_t body_length)
{
    uint8_t frame[20] = {
        0x7eU, 0x80U, 0x01U, 0U, 5U,
        0U, 0U, 0U, 0U, 0U, 0U, 0x45U, 0x67U,
        (uint8_t)(request_serial >> 8), (uint8_t)request_serial,
        (uint8_t)(request_message >> 8), (uint8_t)request_message, result,
        0U, 0x7eU
    };
    uint8_t checksum = 0U;
    uint16_t i;
    frame[18] = 0U;
    frame[3] = (uint8_t)(body_length >> 8);
    frame[4] = (uint8_t)body_length;
    for (i = 1U; i < 18U; ++i) checksum ^= frame[i];
    frame[18] = checksum;
    jt808_on_recv(channel, frame, sizeof(frame));
}

#define inject_ack(s,m,r,l) inject_ack_ch(EC800M_CH_MAIN,(s),(m),(r),(l))

static void inject_location_query(void)
{
    uint8_t frame[15] = {
        0x7eU, 0x82U, 0x01U, 0U, 0U,
        0U, 0U, 0U, 0U, 0U, 0U, 0x12U, 0x34U, 0U, 0x7eU
    };
    uint8_t checksum = 0U;
    uint16_t i;
    for (i = 1U; i < 13U; ++i) checksum ^= frame[i];
    frame[13] = checksum;
    jt808_on_recv(EC800M_CH_MAIN, frame, sizeof(frame));
}

static void inject_empty_command(uint8_t channel, uint16_t message)
{
    uint8_t frame[15] = {
        0x7eU, (uint8_t)(message >> 8), (uint8_t)message, 0U, 0U,
        0U, 0U, 0U, 0U, 0U, 0U, 0x12U, 0x34U, 0U, 0x7eU
    };
    uint8_t checksum = 0U;
    uint16_t i;
    for (i = 1U; i < 13U; ++i) checksum ^= frame[i];
    frame[13] = checksum;
    jt808_on_recv(channel, frame, sizeof(frame));
}

static void inject_one_byte_command(uint8_t channel, uint16_t message, uint8_t value)
{
    uint8_t frame[16] = {
        0x7eU, (uint8_t)(message >> 8), (uint8_t)message, 0U, 1U,
        0U, 0U, 0U, 0U, 0U, 0U, 0x12U, 0x34U, value, 0U, 0x7eU
    };
    uint8_t checksum = 0U;
    uint16_t i;
    for (i = 1U; i < 14U; ++i) checksum ^= frame[i];
    frame[14] = checksum;
    jt808_on_recv(channel, frame, sizeof(frame));
}

static void authenticate(void)
{
    uint16_t auth_serial;
    uint8_t auth_channel, other_channel;
    s_tcp_online = true;
    s_send_result = 0;
    jt808_process();
    auth_serial = sent_serial();
    auth_channel = s_last_send_channel;
    other_channel = auth_channel == EC800M_CH_MAIN ?
                    EC800M_CH_BACKUP : EC800M_CH_MAIN;
    inject_ack_ch(auth_channel, (uint16_t)(auth_serial + 1U),
                  MSG_TERMINAL_AUTH, 0U, 5U);
    assert(!jt808_is_online());
    inject_ack_ch(auth_channel, auth_serial, MSG_LOCATION_REPORT, 0U, 5U);
    assert(!jt808_is_online());
    inject_ack_ch(other_channel, auth_serial, MSG_TERMINAL_AUTH, 0U, 5U);
    assert(!jt808_is_online());
    inject_ack_ch(auth_channel, auth_serial, MSG_TERMINAL_AUTH, 0U, 5U);
    assert(jt808_is_online());
}

static void reboot_replay_state(void)
{
    jt808_init(&(jt808_terminal_t){ .auth_code = "AUTH" });
    authenticate();
}

static void push_record(uint8_t marker)
{
    blind_zone_record_t record;
    unsigned i;
    memset(&record, 0, sizeof(record));
    record.length = 34U;
    for (i = 0U; i < record.length; ++i) record.location[i] = marker + i;
    assert(blind_zone_append(&record) == BLIND_ZONE_OK);
}

static void reset_capture(void)
{
    s_send_count = 0U;
    s_sent_length = 0U;
    s_send_result = 0;
}

int main(void)
{
    jt808_terminal_t terminal;
    uint8_t decoded[1024];
    uint16_t decoded_length, replay_serial, replay_serial2;
    uint8_t first_batch;
    unsigned sends;
    memset(&terminal, 0, sizeof(terminal));
    strcpy(terminal.auth_code, "AUTH");
    memset(&s_gps, 0, sizeof(s_gps));
    s_gps.lat = 22.543096;
    s_gps.lon = 114.057865;
    s_gps.altitude_m = 12.0f;
    s_gps.heading = 91.0f;
    s_gps.speed_kmh = 35.0f;
    s_gps.fix_quality = 1U;
    s_gps.satellites = 12U;
    s_gps.year = 2026U; s_gps.month = 8U; s_gps.day = 28U;
    s_gps.hour = 1U; s_gps.minute = 2U; s_gps.second = 3U;
    s_gps.valid = true;
    jt808_init(&terminal);

    /* Before authentication, ordinary commands from every channel are inert. */
    reset_capture();
    inject_empty_command(EC800M_CH_MAIN, MSG_SET_TERMINAL_PARAM);
    inject_empty_command(EC800M_CH_MAIN, MSG_SET_POLYGON_AREA);
    inject_empty_command(EC800M_CH_MAIN, MSG_LOCATION_QUERY);
    inject_one_byte_command(EC800M_CH_MAIN, MSG_TERMINAL_CTRL, 1U);
    assert(s_param_set_count == 0U && s_geofence_count == 0U &&
           s_relay_count == 0U && s_send_count == 0U);

    /* Interval zero disables periodic live send and offline persistence. */
    jt808_set_report_interval(0U, 0U);
    s_tcp_online = false;
    g_tick_ms = 100000U;
    jt808_process();
    assert(s_append_count == 0U && s_send_count == 0U);
    jt808_set_report_interval(1U, 4U);
    jt808_set_report_interval(30U, 60U);

    /* A definite never-issued store attempt retains and retries the exact event. */
    s_append_script[0] = BLIND_ZONE_IO_ERROR;
    s_append_script[1] = BLIND_ZONE_OK;
    s_append_script_count = 2U; s_append_script_index = 0U;
    s_tcp_online = false;
    s_gps.last_update_ms = g_tick_ms;
    assert(jt808_send_location() == -2);
    s_gps.lat += 1.0;
    assert(jt808_send_location() == 0);
    assert(s_queue_count == 1U && s_append_script_index == 2U);
    s_queue_count = 0U; s_queue_sequence = 1U;

    /* Issued-but-uncertain remains pending until reconciliation confirms one copy. */
    s_append_script[0] = BLIND_ZONE_PENDING;
    s_append_script[1] = BLIND_ZONE_PENDING;
    s_append_script[2] = BLIND_ZONE_OK;
    s_append_script_count = 3U; s_append_script_index = 0U;
    s_gps.last_update_ms = g_tick_ms;
    assert(jt808_send_location() == -2);
    s_gps.lon += 1.0;
    assert(jt808_send_location() == -2);
    assert(jt808_send_location() == 0);
    assert(s_queue_count == 1U && s_append_script_index == 3U);
    s_queue_count = 0U; s_queue_sequence = 1U;
    s_append_script_count = 0U; s_append_script_index = 0U;
    s_append_count = 0U;

    /* A live report that cannot reach an authenticated session is stored once. */
    s_tcp_online = false;
    s_gps.last_update_ms = g_tick_ms;
    assert(jt808_send_location() == 0); /* accepted by durable offline storage */
    assert(s_append_count == 1U && s_queue_count == 1U);
    assert(s_queue[0].length == 34U);
    g_tick_ms += 60001U;
    s_gps.last_update_ms = g_tick_ms;
    jt808_process();
    assert(s_append_count == 2U && s_queue_count == 2U);
    jt808_process();
    assert(s_append_count == 2U); /* one append per eligible periodic event */
    for (uint8_t i = 1U; i < 20U; ++i) push_record((uint8_t)(0x20U + i));

    authenticate();
    /* Ordinary traffic stays on the authenticated backup session even when
     * main opens later, and main-channel commands are rejected. */
    strcpy(s_config.backup_auth_code, "AUTH");
    jt808_init(&terminal);
    s_main_online = false; s_backup_online = true; s_tcp_online = true;
    authenticate();
    s_main_online = true;
    reset_capture();
    assert(jt808_send_heartbeat() == 0);
    assert(s_send_count == 1U && s_last_send_channel == EC800M_CH_BACKUP);
    inject_empty_command(EC800M_CH_MAIN, MSG_SET_TERMINAL_PARAM);
    assert(s_param_set_count == 0U);
    inject_empty_command(EC800M_CH_BACKUP, MSG_SET_TERMINAL_PARAM);
    assert(s_param_set_count == 1U);
    jt808_init(&terminal);
    s_main_online = true; s_backup_online = false;
    authenticate();
    s_send_result = -1;
    {
        unsigned appends = s_append_count;
        inject_location_query();
        assert(s_append_count == appends); /* query response is send-only */
    }
    s_send_result = 0;
    reset_capture();
    blind_zone_replay_process();
    assert(s_send_count == 1U && s_consume_count == 0U);
    decoded_length = unescape(decoded);
    assert(decoded_length <= 513U);
    assert(decoded[0] == 0x07U && decoded[1] == 0x04U);
    first_batch = decoded[12U + 1U];
    assert(decoded[12U] == 0U && first_batch > 0U && first_batch < 20U);
    assert(decoded[14U] == 1U); /* type=blind-zone supplement */
    replay_serial = sent_serial();

    blind_zone_replay_process();
    assert(s_send_count == 1U); /* only one batch may be in flight */

    inject_ack((uint16_t)(replay_serial + 1U), 0x0704U, 0U, 5U);
    inject_ack(replay_serial, 0x0200U, 0U, 5U);
    inject_ack(replay_serial, 0x0704U, 1U, 5U);
    inject_ack(replay_serial, 0x0704U, 0U, 4U);
    blind_zone_replay_process();
    assert(s_consume_count == 0U && s_queue_count == 21U);

    inject_ack(replay_serial, 0x0704U, 0U, 5U);
    s_consume_stale_once = true;
    blind_zone_replay_process();
    assert(s_consume_count == 1U && s_queue_count == 21U);
    reset_capture();
    blind_zone_replay_process();
    assert(s_send_count == 1U); /* stale ACK is cleared and head may replay */
    replay_serial = sent_serial();
    inject_ack(replay_serial, 0x0704U, 0U, 5U);
    s_consume_pending_once = true;
    blind_zone_replay_process();
    assert(s_consume_count == 2U && s_last_consumed == first_batch &&
           s_last_consumed_sequence == 1U && s_queue_count == 21U);

    reset_capture();
    blind_zone_replay_process();
    assert(s_send_count == 0U && s_consume_count == 3U &&
           s_queue_count == 21U - first_batch);
    blind_zone_replay_process();
    assert(s_send_count == 1U);
    replay_serial2 = sent_serial();

    /* A reconnect generation invalidates the old authenticated replay session. */
    ++s_session_generation;
    assert(!jt808_is_online());
    inject_ack(replay_serial2, 0x0704U, 0U, 5U);
    blind_zone_replay_process();
    assert(s_consume_count == 3U);
    authenticate();
    reset_capture();
    blind_zone_replay_process();
    replay_serial2 = sent_serial();
    assert(replay_serial2 != replay_serial);

    /* Reboot forgets only volatile in-flight state; persistent records remain. */
    reboot_replay_state();
    reset_capture();
    blind_zone_replay_process();
    assert(s_send_count == 1U && s_consume_count == 3U);
    replay_serial2 = sent_serial();

    /* Timeout, send failure, and disconnect all retain the exact batch. */
    sends = s_send_count;
    g_tick_ms += BLIND_ZONE_REPLAY_ACK_TIMEOUT_MS + 1U;
    blind_zone_replay_process();
    assert(s_send_count == sends + 1U && s_consume_count == 3U);
    s_tcp_online = false;
    blind_zone_replay_process();
    assert(s_consume_count == 3U);
    s_tcp_online = true;
    s_send_result = -1;
    sends = s_send_count;
    blind_zone_replay_process();
    assert(s_send_count == sends + 1U && s_consume_count == 3U);
    s_send_result = 0;
    blind_zone_replay_process();
    replay_serial2 = sent_serial();
    inject_ack(replay_serial2, 0x0704U, 0U, 5U);
    blind_zone_replay_process();
    assert(s_queue_count == 0U && s_consume_count == 4U);

    puts("test_blind_zone_replay: PASS");
    return 0;
}
'''


def compile_and_run(replay_source: Path) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        (tmp / "harness.c").write_text(HARNESS, encoding="utf-8")
        (tmp / "n32l40x.h").write_text(
            "#ifndef N32L40X_H\n#define N32L40X_H\n"
            "#define GPIOA ((void *)0)\n#define GPIO_PIN_3 3U\n#define GPIO_PIN_12 12U\n#define Bit_RESET 0\n"
            "int GPIO_ReadInputDataBit(void *, unsigned);\n#endif\n",
            encoding="ascii",
        )
        executable = tmp / "blind_zone_replay.exe"
        subprocess.run(
            [
                compiler(), "-std=c99", "-Wall", "-Wextra", "-Werror",
                "-I", str(tmp), "-I", str(ROOT / "include"),
                str(ROOT / "src" / "jt808.c"),
                str(ROOT / "src" / "jt808_session.c"),
                str(ROOT / "src" / "terminal_identity.c"), str(replay_source),
                str(tmp / "harness.c"), "-lm", "-o", str(executable),
            ], check=True,
        )
        return subprocess.run([str(executable)], capture_output=True, text=True)


def main() -> None:
    result = compile_and_run(ROOT / "src/blind_zone_replay.c")
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)
    print(result.stdout, end="")

    # Mutation proof: accepting a mismatched ACK serial must break the harness.
    source = (ROOT / "src/blind_zone_replay.c").read_text(encoding="utf-8")
    needle = "reply_serial != s_inflight.serial"
    assert needle in source
    with tempfile.TemporaryDirectory() as directory:
        mutant = Path(directory) / "blind_zone_replay_mutant.c"
        mutant.write_text(source.replace(needle, "reply_serial == s_inflight.serial", 1),
                          encoding="utf-8")
        result = compile_and_run(mutant)
        assert result.returncode != 0, "ACK-serial mutation unexpectedly survived"
    print("test_blind_zone_replay mutation: PASS")


if __name__ == "__main__":
    main()
