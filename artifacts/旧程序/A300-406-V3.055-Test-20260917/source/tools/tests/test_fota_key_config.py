#!/usr/bin/env python3
"""Host contract test for FKEY parsing and atomic configuration."""

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
#include <string.h>

#include "f39_command.h"
#include "f39_config_adapter.h"

typedef struct {
    unsigned calls;
    bool result;
} persist_spy_t;

static bool persist(const device_config_t *candidate, void *context)
{
    persist_spy_t *spy = (persist_spy_t *)context;
    (void)candidate;
    ++spy->calls;
    return spy->result;
}

static bool prepare(const char *text, device_config_t *live,
                    persist_spy_t *spy, f39_transaction_t *transaction)
{
    f39_request_t request;
    f39_transaction_init(transaction, live, persist, spy);
    return f39_parse((const uint8_t *)text, (uint16_t)strlen(text),
                     &request) == F39_RESULT_OK &&
           f39_prepare_config(&request, live, transaction);
}

static void assert_rejected(const char *text)
{
    device_config_t live;
    device_config_t before;
    persist_spy_t spy = { 0U, true };
    f39_transaction_t transaction;

    memset(&live, 0, sizeof(live));
    strcpy(live.device_api_key, "ORIGINAL-KEY-1234");
    before = live;
    assert(!prepare(text, &live, &spy, &transaction));
    assert(spy.calls == 0U);
    assert(memcmp(&live, &before, sizeof(live)) == 0);
}

int main(void)
{
    device_config_t live;
    device_config_t before;
    persist_spy_t spy = { 0U, true };
    f39_transaction_t transaction;
    f39_request_t query;

    memset(&live, 0, sizeof(live));
    assert(f39_parse((const uint8_t *)"FKEY?", 5U, &query) == F39_RESULT_OK);
    assert(query.operation == F39_OPERATION_FKEY);
    assert(query.argc == 0U);

    assert_rejected("FKEY,1234567890ABCDE");
    assert_rejected("FKEY,12345678901234567890123456789012");
    assert_rejected("FKEY,1234567\x1f" "89012345");
    assert_rejected("FKEY,a,b");

    assert(prepare("FKEY,1234567890ABCDEF", &live, &spy, &transaction));
    assert(transaction.effects == F39_EFFECT_FOTA_RECHECK);
    assert(strcmp(transaction.candidate.device_api_key,
                  "1234567890ABCDEF") == 0);
    assert(f39_commit_config(&transaction) == F39_RESULT_OK);
    assert(spy.calls == 1U);
    assert(strcmp(live.device_api_key, "1234567890ABCDEF") == 0);

    assert(prepare("FKEY,1234567 89012345", &live, &spy, &transaction));
    assert(f39_commit_config(&transaction) == F39_RESULT_OK);
    assert(strcmp(live.device_api_key, "1234567 89012345") == 0);

    assert(prepare("FKEY,1234567*89012345", &live, &spy, &transaction));
    assert(f39_commit_config(&transaction) == F39_RESULT_OK);
    assert(strcmp(live.device_api_key, "1234567*89012345") == 0);

    assert(prepare("FKEY,1234567890123456789012345678901", &live, &spy,
                   &transaction));
    assert(strlen(transaction.candidate.device_api_key) == 31U);

    before = live;
    spy.result = false;
    assert(prepare("FKEY,ZYXWVUTSRQPONMLK", &live, &spy, &transaction));
    assert(f39_commit_config(&transaction) == F39_RESULT_INVALID);
    assert(memcmp(&live, &before, sizeof(live)) == 0);
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
            print("test_fota_key_config: FAIL (no C compiler available)")
            return 1
        print("test_fota_key_config: SKIP (no C compiler available)")
        return 0

    with tempfile.TemporaryDirectory(prefix="fota_key_config_") as temp_dir:
        temp = pathlib.Path(temp_dir)
        harness = temp / "fota_key_config_harness.c"
        binary = temp / "fota_key_config_harness.exe"
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
            print("test_fota_key_config: FAIL (C harness did not compile)")
            return build.returncode
        run = subprocess.run([str(binary)], cwd=ROOT, text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if run.returncode != 0:
            print(run.stdout, end="")
            print("test_fota_key_config: FAIL (C harness assertion)")
            return run.returncode

    print("test_fota_key_config: C99 -Wall -Wextra -Werror PASS")
    print("test_fota_key_config: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
