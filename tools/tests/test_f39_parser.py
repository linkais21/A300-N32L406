#!/usr/bin/env python3
"""Host contract test for the bounded, platform-neutral F39 parser."""

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[2]

HARNESS = r'''
#include <assert.h>
#include <stdio.h>
#include <stdint.h>
#include <string.h>

#include "f39_command.h"

static f39_result_t parse_text(const char *text, f39_request_t *out)
{
    return f39_parse((const uint8_t *)text, (uint16_t)strlen(text), out);
}

static void expect_ok(const char *text, f39_operation_t operation,
                      uint8_t argc, const char *arg0)
{
    f39_request_t req;
    f39_result_t result = parse_text(text, &req);

    assert(result == F39_RESULT_OK);
    assert(req.operation == operation);
    assert(req.argc == argc);
    if (arg0 != 0) {
        assert(req.args[0].len == strlen(arg0));
        assert(memcmp(&req.raw[req.args[0].offset], arg0, req.args[0].len) == 0);
    }
}

static void expect_reject(const uint8_t *data, uint16_t len)
{
    f39_request_t req;
    f39_result_t result = f39_parse(data, len, &req);
    if (result == F39_RESULT_OK) { fprintf(stderr, "unexpected accepted: %.*s\\n", (int)len, data); }
    assert(result != F39_RESULT_OK);
    assert(req.operation == F39_OPERATION_INVALID);
    assert(req.argc == 0U);
}

static void expect_longest_valid(const uint8_t *data, uint16_t len)
{
    f39_request_t req;
    assert(len == F39_COMMAND_MAX_LENGTH);
    assert(f39_parse(data, len, &req) == F39_RESULT_OK);
    assert(req.operation == F39_OPERATION_CAR);
    assert(req.argc == 1U);
    assert(req.raw_len == F39_COMMAND_MAX_LENGTH);
    assert(req.args[0].len == (F39_COMMAND_MAX_LENGTH - 4U));
}

int main(void)
{
    static const struct {
        const char *text;
        f39_operation_t operation;
        uint8_t argc;
        const char *arg0;
    } accepted[] = {
        {"PARAM", F39_OPERATION_PARAM, 0U, 0},
        {"DUALSET,IP,a,1*HBT,60", F39_OPERATION_DUALSET, 1U, "IP,a,1*HBT,60"},
        {"RESET", F39_OPERATION_RESET, 0U, 0},
        {"PID", F39_OPERATION_PID, 0U, 0},
        {"PID,123", F39_OPERATION_PID, 1U, "123"},
        {"IP", F39_OPERATION_IP, 0U, 0},
        {"ip,server.example,9000", F39_OPERATION_IP, 2U, "server.example"},
        {"FIP", F39_OPERATION_FIP, 0U, 0},
        {"FIP,backup.example,9001", F39_OPERATION_FIP, 2U, "backup.example"},
        {"FREQ", F39_OPERATION_FREQ, 0U, 0},
        {"FREQ,30,600", F39_OPERATION_FREQ, 2U, "30"},
        {"HBT", F39_OPERATION_HBT, 0U, 0},
        {"HBT,60", F39_OPERATION_HBT, 1U, "60"},
        {"MODEL", F39_OPERATION_MODEL, 0U, 0},
        {"MODEL,1", F39_OPERATION_MODEL, 1U, "1"},
        {"SPEED", F39_OPERATION_SPEED, 0U, 0},
        {"SPEED,80", F39_OPERATION_SPEED, 1U, "80"},
        {"APN", F39_OPERATION_APN, 0U, 0},
        {"APN,internet,user,password", F39_OPERATION_APN, 3U, "internet"},
        {"RELAY", F39_OPERATION_RELAY, 0U, 0},
        {"RELAY,1", F39_OPERATION_RELAY, 1U, "1"},
        {"GPSDUP", F39_OPERATION_GPSDUP, 0U, 0},
        {"GPSDUP,10", F39_OPERATION_GPSDUP, 1U, "10"},
        {"MLG", F39_OPERATION_MLG, 0U, 0},
        {"MLG,1", F39_OPERATION_MLG, 1U, "1"},
        {"CAR", F39_OPERATION_CAR, 0U, 0},
        {"CAR,ABC123", F39_OPERATION_CAR, 1U, "ABC123"},
        {"GPSBDS", F39_OPERATION_GPSBDS, 0U, 0},
        {"GPSBDS,2", F39_OPERATION_GPSBDS, 1U, "2"},
        {"GMTSET", F39_OPERATION_GMTSET, 0U, 0},
        {"GMTSET,8", F39_OPERATION_GMTSET, 1U, "8"},
    };
    static const char *rejected[] = {
        "", "PARAM,x", "RESET,x", "IP,", "IP,,9000", "IP,a,9000,",
        "IP=a,9000", "IP,a#", "IP,a\r", "IP,a\n", "IPX,a", "IP,a junk",
        "IP,a*HBT,60",
        "DUALSET", "DUALSET,", "DUALSET,*IP,a,1", "DUALSET,IP,a,1*",
        "VIBSENS,1", "CANCEL", "DISMODE,1", "POWERMODE,1", "VELOCITY,1",
        "BALE,1", "BALESET,1", "RTK,1", "C21,1",
    };
    uint8_t nul_data[] = {'I', 'P', ',', 'a', 0, ',', '1'};
    uint8_t max_data[192];
    uint8_t longest_valid[F39_COMMAND_MAX_LENGTH];
    size_t i;

    for (i = 0U; i < sizeof(accepted) / sizeof(accepted[0]); ++i) {
        expect_ok(accepted[i].text, accepted[i].operation, accepted[i].argc,
                  accepted[i].arg0);
    }
    for (i = 0U; i < sizeof(rejected) / sizeof(rejected[0]); ++i) {
        expect_reject((const uint8_t *)rejected[i], (uint16_t)strlen(rejected[i]));
    }
    expect_reject(nul_data, (uint16_t)sizeof(nul_data));
    memcpy(longest_valid, "CAR,", 4U);
    memset(&longest_valid[4], 'A', sizeof(longest_valid) - 4U);
    expect_longest_valid(longest_valid, (uint16_t)sizeof(longest_valid));
    memset(max_data, 'A', sizeof(max_data));
    expect_reject(max_data, (uint16_t)sizeof(max_data));
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
            print("test_f39_parser: FAIL (no C compiler available)")
            return 1
        print("test_f39_parser: SKIP (no C compiler available)")
        return 0

    with tempfile.TemporaryDirectory(prefix="f39_parser_") as temp_dir:
        temp = pathlib.Path(temp_dir)
        harness = temp / "f39_parser_harness.c"
        binary = temp / "f39_parser_harness"
        harness.write_text(HARNESS, encoding="utf-8")
        command = [
            compiler, "-std=c99", "-Wall", "-Wextra", "-Werror",
            "-I", str(ROOT / "include"), str(harness),
            str(ROOT / "src" / "f39_command.c"), "-o", str(binary),
        ]
        build = subprocess.run(command, cwd=ROOT, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if build.returncode != 0:
            print(build.stdout, end="")
            print("test_f39_parser: FAIL (C harness did not compile)")
            return build.returncode
        run = subprocess.run([str(binary)], cwd=ROOT, text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if run.returncode != 0:
            print(run.stdout, end="")
            print("test_f39_parser: FAIL (C harness assertion)")
            return run.returncode
    print("test_f39_parser: C harness PASS")
    print("test_f39_parser: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
