#!/usr/bin/env python3
"""Host contract tests for atomic F39 DUALSET transactions."""

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
} spy_t;

static bool persist(const device_config_t *candidate, void *context)
{
    spy_t *spy = (spy_t *)context;
    ++spy->calls;
    spy->saved = *candidate;
    return spy->result;
}

static device_config_t seed(void)
{
    device_config_t cfg;
    memset(&cfg, 0x5a, sizeof(cfg));
    strcpy(cfg.server_ip, "old");
    cfg.server_port = 1111U;
    cfg.report_moving_s = 30U;
    cfg.report_stopped_s = 300U;
    cfg.heartbeat_s = 60U;
    cfg.gpsbds_mode = 2U;
    strcpy(cfg.terminal_model, "OLD");
    return cfg;
}

static bool prepare(const char *text, device_config_t *live, spy_t *spy,
                    f39_transaction_t *tx)
{
    f39_request_t request;
    f39_transaction_init(tx, live, persist, spy);
    if (f39_parse((const uint8_t *)text, (uint16_t)strlen(text), &request) !=
        F39_RESULT_OK) {
        return false;
    }
    return f39_prepare_config(&request, live, tx);
}

static void expect_invalid(const char *text)
{
    device_config_t live = seed();
    device_config_t before = live;
    spy_t spy = {0U, true, {0}};
    f39_transaction_t tx;
    assert(!prepare(text, &live, &spy, &tx));
    assert(spy.calls == 0U);
    assert(tx.effects == F39_EFFECT_NONE);
    assert(memcmp(&live, &before, sizeof(live)) == 0);
    assert(f39_commit_config(&tx) == F39_RESULT_INVALID);
    assert(spy.calls == 0U);
    assert(memcmp(&live, &before, sizeof(live)) == 0);
}

static void test_late_failure_is_atomic(void)
{
    device_config_t live = seed();
    device_config_t before = live;
    spy_t spy = {0U, true, {0}};
    f39_transaction_t tx;
    assert(!prepare("DUALSET,IP,new.example,9000*HBT,29", &live, &spy, &tx));
    assert(spy.calls == 0U);
    assert(tx.effects == F39_EFFECT_NONE);
    assert(memcmp(&tx.candidate, &before, sizeof(before)) == 0);
    assert(memcmp(&live, &before, sizeof(live)) == 0);
}

static void test_success_single_commit_and_effects(void)
{
    device_config_t live = seed();
    spy_t spy = {0U, true, {0}};
    f39_transaction_t tx;
    uint32_t expected = F39_EFFECT_TIMER_REFRESH |
                        F39_EFFECT_NETWORK_RECONNECT |
                        F39_EFFECT_MAIN_AUTH_RESET |
                        F39_EFFECT_GNSS_REFRESH |
                        F39_EFFECT_JT808_REREGISTER |
                        F39_EFFECT_REMAINING_REFRESH;
    assert(prepare("DUALSET,FREQ,5,60*IP,main.example,1234*GPSBDS,3*MODEL,T360",
                   &live, &spy, &tx));
    assert(spy.calls == 0U);
    assert(tx.effects == expected);
    assert(strcmp(tx.candidate.server_ip, "main.example") == 0);
    assert(tx.candidate.server_port == 1234U);
    assert(tx.candidate.report_moving_s == 5U);
    assert(tx.candidate.report_stopped_s == 60U);
    assert(tx.candidate.gpsbds_mode == 3U);
    assert(strcmp(tx.candidate.terminal_model, "T360") == 0);
    assert(f39_commit_config(&tx) == F39_RESULT_OK);
    assert(spy.calls == 1U);
    assert(live.server_port == 1234U && live.gpsbds_mode == 3U);
    assert(f39_commit_config(&tx) == F39_RESULT_INVALID);
    assert(spy.calls == 1U);
}

static void test_reject_duplicate_nested_actions_and_malformed(void)
{
    static const char *const invalid[] = {
        "DUALSET,IP,a,1*IP,b,2",
        "DUALSET,DUALSET,IP,a,1",
        "DUALSET,RESET",
        "DUALSET,RELAY,1",
        "DUALSET,PARAM",
        "DUALSET,PID,12345678901",
        "DUALSET,UNKNOWN,1",
        "DUALSET,IP,a,1**HBT,60",
        "DUALSET,*IP,a,1",
        "DUALSET,IP,a,1*",
        "DUALSET,IP,a,1*HBT",
        "DUALSET,IP,a,1*IPX,b,2",
        "DUALSET,IP,a,1*FREQ,1,5*HBT,30*MODEL,M*GPSBDS,1*APN,a*GPSDUP,1*MLG,1*CAR,A"
    };
    size_t i;
    for (i = 0U; i < sizeof(invalid) / sizeof(invalid[0]); ++i) {
        expect_invalid(invalid[i]);
    }
}

static void test_persistence_failure_retains_old_state(void)
{
    device_config_t live = seed();
    device_config_t before = live;
    spy_t spy = {0U, false, {0}};
    f39_transaction_t tx;
    assert(prepare("DUALSET,FREQ,5,60*IP,new.example,9000", &live, &spy, &tx));
    assert(f39_commit_config(&tx) == F39_RESULT_INVALID);
    assert(spy.calls == 1U);
    assert(tx.effects == F39_EFFECT_NONE);
    assert(memcmp(&live, &before, sizeof(live)) == 0);
}

int main(void)
{
    test_late_failure_is_atomic();
    test_success_single_commit_and_effects();
    test_reject_duplicate_nested_actions_and_malformed();
    test_persistence_failure_retains_old_state();
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
            print("test_f39_dualset: FAIL (no C compiler available)")
            return 1
        print("test_f39_dualset: SKIP (no C compiler available)")
        return 0
    with tempfile.TemporaryDirectory(prefix="f39_dualset_") as temp_dir:
        temp = pathlib.Path(temp_dir)
        harness = temp / "f39_dualset_harness.c"
        binary = temp / "f39_dualset_harness.exe"
        harness.write_text(HARNESS, encoding="utf-8")
        command = [
            compiler, "-std=c99", "-Wall", "-Wextra", "-Werror",
            "-I", str(ROOT / "include"), str(harness),
            str(ROOT / "src" / "f39_command.c"),
            str(ROOT / "src/plate_encoding.c"), str(ROOT / "src" / "f39_config_adapter.c"), "-o", str(binary),
        ]
        build = subprocess.run(command, cwd=ROOT, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if build.returncode != 0:
            print(build.stdout, end="")
            print("test_f39_dualset: FAIL (C harness did not compile)")
            return build.returncode
        run = subprocess.run([str(binary)], cwd=ROOT, text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if run.returncode != 0:
            print(run.stdout, end="")
            print("test_f39_dualset: FAIL (C harness assertion)")
            return run.returncode
    print("test_f39_dualset: C99 -Wall -Wextra -Werror PASS")
    print("test_f39_dualset: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
