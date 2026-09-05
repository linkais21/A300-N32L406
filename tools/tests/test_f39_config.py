#!/usr/bin/env python3
"""Host contract test for the transactional F39 configuration adapter."""

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[2]

HARNESS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "f39_command.h"
#include "f39_config_adapter.h"

typedef struct {
    unsigned calls;
    bool result;
    device_config_t saved;
} persistence_spy_t;

static bool persist(const device_config_t *candidate, void *context)
{
    persistence_spy_t *spy = (persistence_spy_t *)context;
    ++spy->calls;
    spy->saved = *candidate;
    return spy->result;
}

static device_config_t seed_config(void)
{
    device_config_t cfg;
    memset(&cfg, 0x5a, sizeof(cfg));
    strcpy(cfg.server_ip, "old-main");
    cfg.server_port = 1111U;
    strcpy(cfg.backup_ip, "old-backup");
    cfg.backup_port = 2222U;
    cfg.heartbeat_s = 60U;
    cfg.report_moving_s = 30U;
    cfg.report_stopped_s = 300U;
    cfg.autoapn_en = 1U;
    cfg.apn[0] = cfg.apn_user[0] = cfg.apn_pass[0] = '\0';
    cfg.pid[0] = '\0';
    strcpy(cfg.terminal_model, "A300_406");
    cfg.speed_limit_kmh = 120U;
    cfg.sleep_report_mode = 0U;
    cfg.mileage_m = 123400U;
    strcpy(cfg.plate_no, "OLD");
    cfg.gpsbds_mode = 2U;
    cfg.gmt_sign = 1;
    cfg.gmt_hour = 8U;
    cfg.gmt_min = 0U;
    return cfg;
}

static bool prepare_text(const char *text, device_config_t *live,
                         persistence_spy_t *spy, f39_transaction_t *tx)
{
    f39_request_t request;
    f39_transaction_init(tx, live, persist, spy);
    if (f39_parse((const uint8_t *)text, (uint16_t)strlen(text),
                  &request) != F39_RESULT_OK) {
        return false;
    }
    return f39_prepare_config(&request, live, tx);
}

static void expect_invalid(const char *text)
{
    device_config_t live = seed_config();
    device_config_t before = live;
    persistence_spy_t spy = {0U, true, {0}};
    f39_transaction_t tx;

    if (prepare_text(text, &live, &spy, &tx)) {
        fprintf(stderr, "unexpected prepared: %s\\n", text);
        assert(0);
    }
    assert(spy.calls == 0U);
    assert(tx.effects == F39_EFFECT_NONE);
    assert(memcmp(&live, &before, sizeof(live)) == 0);
    assert(f39_commit_config(&tx) == F39_RESULT_INVALID);
    assert(spy.calls == 0U);
    assert(memcmp(&live, &before, sizeof(live)) == 0);
}

static f39_transaction_t expect_prepared(const char *text,
                                         device_config_t *live,
                                         persistence_spy_t *spy,
                                         uint32_t effects)
{
    f39_transaction_t tx;
    device_config_t before = *live;
    assert(prepare_text(text, live, spy, &tx));
    assert(spy->calls == 0U);
    assert(memcmp(live, &before, sizeof(*live)) == 0);
    assert(tx.effects == effects);
    return tx;
}

static void test_valid_mapping_and_effects(void)
{
    device_config_t live = seed_config();
    persistence_spy_t spy = {0U, true, {0}};
    f39_transaction_t tx;

    tx = expect_prepared("IP,host.example,65535", &live, &spy,
                         F39_EFFECT_NETWORK_RECONNECT);
    assert(strcmp(tx.candidate.server_ip, "host.example") == 0);
    assert(tx.candidate.server_port == 65535U);

    tx = expect_prepared("FIP,backup.example,1", &live, &spy,
                         F39_EFFECT_NETWORK_RECONNECT);
    assert(strcmp(tx.candidate.backup_ip, "backup.example") == 0);
    assert(tx.candidate.backup_port == 1U);
    tx = expect_prepared("FIP,0", &live, &spy,
                         F39_EFFECT_NETWORK_RECONNECT);
    assert(tx.candidate.backup_ip[0] == '\0' && tx.candidate.backup_port == 0U);

    tx = expect_prepared("FREQ,1,65535", &live, &spy,
                         F39_EFFECT_TIMER_REFRESH);
    assert(tx.candidate.report_moving_s == 1U);
    assert(tx.candidate.report_stopped_s == 65535U);
    tx = expect_prepared("FREQ,300,5", &live, &spy,
                         F39_EFFECT_TIMER_REFRESH);
    assert(tx.candidate.report_moving_s == 300U && tx.candidate.report_stopped_s == 5U);
    tx = expect_prepared("IP,edge,1", &live, &spy,
                         F39_EFFECT_NETWORK_RECONNECT);
    assert(tx.candidate.server_port == 1U);
    tx = expect_prepared("HBT,30", &live, &spy, F39_EFFECT_TIMER_REFRESH);
    assert(tx.candidate.heartbeat_s == 30U);
    tx = expect_prepared("HBT,3600", &live, &spy, F39_EFFECT_TIMER_REFRESH);
    assert(tx.candidate.heartbeat_s == 3600U);

    tx = expect_prepared("MODEL,T360-A300", &live, &spy,
                         F39_EFFECT_JT808_REREGISTER |
                         F39_EFFECT_REMAINING_REFRESH);
    assert(strcmp(tx.candidate.terminal_model, "T360-A300") == 0);
    tx = expect_prepared("SPEED,20", &live, &spy, F39_EFFECT_NONE);
    assert(tx.candidate.speed_limit_kmh == 20U);
    tx = expect_prepared("SPEED,200", &live, &spy, F39_EFFECT_NONE);
    assert(tx.candidate.speed_limit_kmh == 200U);

    tx = expect_prepared("APN,cmnet,user,password", &live, &spy,
                         F39_EFFECT_NETWORK_RECONNECT);
    assert(tx.candidate.autoapn_en == 0U);
    assert(strcmp(tx.candidate.apn, "cmnet") == 0);
    assert(strcmp(tx.candidate.apn_user, "user") == 0);
    assert(strcmp(tx.candidate.apn_pass, "password") == 0);
    tx = expect_prepared("APN,AUTO", &live, &spy,
                         F39_EFFECT_NETWORK_RECONNECT);
    assert(tx.candidate.autoapn_en == 1U);
    assert(tx.candidate.apn[0] == '\0' && tx.candidate.apn_user[0] == '\0' &&
           tx.candidate.apn_pass[0] == '\0');
    tx = expect_prepared("APN,0", &live, &spy,
                         F39_EFFECT_NETWORK_RECONNECT);
    assert(tx.candidate.autoapn_en == 1U);

    tx = expect_prepared("GPSDUP,0", &live, &spy, F39_EFFECT_NONE);
    assert(tx.candidate.sleep_report_mode == 1U);
    tx = expect_prepared("GPSDUP,1", &live, &spy, F39_EFFECT_NONE);
    assert(tx.candidate.sleep_report_mode == 0U);
    tx = expect_prepared("MLG,42949672", &live, &spy, F39_EFFECT_NONE);
    assert(tx.candidate.mileage_m == 4294967200UL);

    tx = expect_prepared("CAR,01B12345", &live, &spy, F39_EFFECT_NONE);
    assert(strcmp(tx.candidate.plate_no, "\xe4\xba\xac" "B12345") == 0);
    tx = expect_prepared("CAR,39A1", &live, &spy, F39_EFFECT_NONE);
    assert(strcmp(tx.candidate.plate_no, "\xe5\x8f\xb0" "A1") == 0);
    tx = expect_prepared("CAR,ABC123", &live, &spy, F39_EFFECT_NONE);
    assert(strcmp(tx.candidate.plate_no, "ABC123") == 0);

    tx = expect_prepared("GPSBDS,1", &live, &spy, F39_EFFECT_GNSS_REFRESH);
    assert(tx.candidate.gpsbds_mode == 1U);
    tx = expect_prepared("GPSBDS,2", &live, &spy, F39_EFFECT_GNSS_REFRESH);
    assert(tx.candidate.gpsbds_mode == 2U);
    tx = expect_prepared("GPSBDS,3", &live, &spy,
                         F39_EFFECT_GNSS_REFRESH);
    assert(tx.candidate.gpsbds_mode == 3U);
    tx = expect_prepared("GMTSET,W1259", &live, &spy, F39_EFFECT_NONE);
    assert(tx.candidate.gmt_sign == -1 && tx.candidate.gmt_hour == 12U &&
           tx.candidate.gmt_min == 59U);
    tx = expect_prepared("PID,01234567890", &live, &spy,
                         F39_EFFECT_JT808_REREGISTER |
                         F39_EFFECT_REMAINING_REFRESH);
    assert(strcmp(tx.candidate.pid, "01234567890") == 0);
}

static void test_boundaries_and_invalid_inputs_are_atomic(void)
{
    static const char *invalid[] = {
        "IP", "IP,,1", "IP,a,0", "IP,a,65536",
        "IP,aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa,1",
        "FIP", "FIP,0,1", "FIP,a,0", "FIP,a,65536",
        "FREQ,0,5", "FREQ,301,5", "FREQ,1,4", "FREQ,1,65536",
        "HBT,29", "HBT,3601", "MODEL", "MODEL,abc def",
        "MODEL,ABCDEFGHIJKLMNOPQRSTU", "SPEED,19", "SPEED,201",
        "APN", "APN,AUTO,user", "APN,0,user",
        "APN,aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "APN,a,b,c,d",
        "GPSDUP,2", "MLG,-1", "MLG,42949673", "MLG,1x",
        "CAR,00A1", "CAR,40A1", "CAR,01ABCDEFGHIJKLM",
        "GPSBDS,0", "GPSBDS,4", "GMTSET,E1260", "GMTSET,E1300",
        "GMTSET,X0800", "GMTSET,E800", "PID,1234567890",
        "PID,123456789012", "PID,1234567890A", "PID"
    };
    size_t i;
    for (i = 0U; i < sizeof(invalid) / sizeof(invalid[0]); ++i) {
        expect_invalid(invalid[i]);
    }
}

static void test_valid_capacity_boundaries_and_all_provinces(void)
{
    static const char *const provinces[] = {
        "", "\xe4\xba\xac", "\xe6\xb5\x99", "\xe6\xb4\xa5", "\xe7\x9a\x96",
        "\xe6\xb2\xaa", "\xe9\x97\xbd", "\xe6\xb8\x9d", "\xe8\xb5\xa3",
        "\xe6\xb8\xaf", "\xe9\xb2\x81", "\xe6\xbe\xb3", "\xe8\xb1\xab",
        "\xe8\x92\x99", "\xe9\x84\x82", "\xe6\x96\xb0", "\xe6\xb9\x98",
        "\xe5\xae\x81", "\xe7\xb2\xa4", "\xe8\x97\x8f", "\xe7\x90\xbc",
        "\xe6\xa1\x82", "\xe5\xb7\x9d", "\xe8\x9c\x80", "\xe5\x86\x80",
        "\xe8\xb4\xb5", "\xe9\xbb\x94", "\xe6\x99\x8b", "\xe4\xba\x91",
        "\xe6\xbb\x87", "\xe8\xbe\xbd", "\xe9\x99\x95", "\xe7\xa7\xa6",
        "\xe5\x90\x89", "\xe7\x94\x98", "\xe9\x99\x87", "\xe9\xbb\x91",
        "\xe9\x9d\x92", "\xe8\x8b\x8f", "\xe5\x8f\xb0"
    };
    char text[96];
    device_config_t live = seed_config();
    persistence_spy_t spy = {0U, true, {0}};
    f39_transaction_t tx;
    unsigned code;

    strcpy(text, "IP,");
    memset(text + 3, 'h', 63U);
    strcpy(text + 66, ",1");
    tx = expect_prepared(text, &live, &spy, F39_EFFECT_NETWORK_RECONNECT);
    assert(strlen(tx.candidate.server_ip) == 63U);

    strcpy(text, "APN,");
    memset(text + 4, 'a', 31U);
    text[35] = '\0';
    tx = expect_prepared(text, &live, &spy, F39_EFFECT_NETWORK_RECONNECT);
    assert(strlen(tx.candidate.apn) == 31U);

    strcpy(text, "APN,a,");
    memset(text + 6, 'u', 31U);
    text[37] = ',';
    memset(text + 38, 'p', 31U);
    text[69] = '\0';
    tx = expect_prepared(text, &live, &spy, F39_EFFECT_NETWORK_RECONNECT);
    assert(strlen(tx.candidate.apn_user) == 31U);
    assert(strlen(tx.candidate.apn_pass) == 31U);

    tx = expect_prepared("MODEL,ABCDEFGHIJKLMNOPQRST", &live, &spy,
                         F39_EFFECT_JT808_REREGISTER |
                         F39_EFFECT_REMAINING_REFRESH);
    assert(strlen(tx.candidate.terminal_model) == 20U);

    for (code = 1U; code <= 39U; ++code) {
        (void)sprintf(text, "CAR,%02uA", code);
        tx = expect_prepared(text, &live, &spy, F39_EFFECT_NONE);
        assert(strncmp(tx.candidate.plate_no, provinces[code],
                       strlen(provinces[code])) == 0);
        assert(strcmp(tx.candidate.plate_no + strlen(provinces[code]), "A") == 0);
    }
}

static void test_commit_boundary_and_failure(void)
{
    device_config_t live = seed_config();
    device_config_t before = live;
    persistence_spy_t spy = {0U, true, {0}};
    f39_transaction_t tx = expect_prepared("HBT,120", &live, &spy,
                                           F39_EFFECT_TIMER_REFRESH);

    assert(f39_commit_config(&tx) == F39_RESULT_OK);
    assert(spy.calls == 1U);
    assert(spy.saved.heartbeat_s == 120U);
    assert(live.heartbeat_s == 120U);
    assert(f39_commit_config(&tx) == F39_RESULT_INVALID);
    assert(spy.calls == 1U);

    live = before;
    spy.calls = 0U;
    spy.result = false;
    tx = expect_prepared("IP,new.example,9000", &live, &spy,
                         F39_EFFECT_NETWORK_RECONNECT);
    assert(f39_commit_config(&tx) == F39_RESULT_INVALID);
    assert(spy.calls == 1U);
    assert(memcmp(&live, &before, sizeof(live)) == 0);
}

static void test_null_contracts(void)
{
    device_config_t live = seed_config();
    persistence_spy_t spy = {0U, true, {0}};
    f39_transaction_t tx;
    f39_request_t request;
    assert(f39_parse((const uint8_t *)"HBT,60", 6U, &request) == F39_RESULT_OK);
    f39_transaction_init(&tx, &live, persist, &spy);
    assert(!f39_prepare_config(NULL, &live, &tx));
    assert(!f39_prepare_config(&request, NULL, &tx));
    assert(!f39_prepare_config(&request, &live, NULL));
    f39_transaction_init(&tx, &live, NULL, &spy);
    assert(!f39_prepare_config(&request, &live, &tx));
    assert(f39_commit_config(NULL) == F39_RESULT_INVALID);
}

int main(void)
{
    test_valid_mapping_and_effects();
    test_boundaries_and_invalid_inputs_are_atomic();
    test_valid_capacity_boundaries_and_all_provinces();
    test_commit_boundary_and_failure();
    test_null_contracts();
    return 0;
}
'''


def find_compiler():
    for candidate in ("gcc", "cc"):
        found = shutil.which(candidate)
        if found:
            return found
    return None


def main():
    compiler = find_compiler()
    if compiler is None:
        if os.environ.get("REQUIRE_GCC") == "1":
            print("test_f39_config: FAIL (no C compiler available)")
            return 1
        print("test_f39_config: SKIP (no C compiler available)")
        return 0

    with tempfile.TemporaryDirectory(prefix="f39_config_") as temp_dir:
        temp = pathlib.Path(temp_dir)
        harness = temp / "f39_config_harness.c"
        binary = temp / "f39_config_harness.exe"
        harness.write_text(HARNESS, encoding="utf-8")
        command = [
            compiler, "-std=c99", "-Wall", "-Wextra", "-Werror",
            "-I", str(ROOT / "include"), str(harness),
            str(ROOT / "src" / "f39_command.c"),
            str(ROOT / "src" / "f39_config_adapter.c"), "-o", str(binary),
        ]
        build = subprocess.run(command, cwd=ROOT, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if build.returncode != 0:
            print(build.stdout, end="")
            print("test_f39_config: FAIL (C harness did not compile)")
            return build.returncode
        run = subprocess.run([str(binary)], cwd=ROOT, text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if run.returncode != 0:
            print(run.stdout, end="")
            print("test_f39_config: FAIL (C harness assertion)")
            return run.returncode

    print("test_f39_config: C99 -Wall -Wextra -Werror PASS")
    print("test_f39_config: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
