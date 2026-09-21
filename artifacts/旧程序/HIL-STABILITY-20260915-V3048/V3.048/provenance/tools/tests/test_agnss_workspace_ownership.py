"""Compile/execute ownership contracts for shared AGNSS SRAM."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]

HARNESS = r'''
#include <assert.h>
#include <stddef.h>
#include <string.h>
#include "agnss_stream_workspace.h"
#include "service_workspace.h"

int main(void)
{
    size_t capacity = 0U;

    assert(agnss_stream_workspace_try_acquire(AGNSS_STREAM_OWNER_HUADA));
    assert(agnss_stream_workspace_buffer(AGNSS_STREAM_OWNER_HUADA,
                                         &capacity) != NULL);
    assert(capacity >= 4096U);
    assert(!agnss_stream_workspace_try_acquire(AGNSS_STREAM_OWNER_ZHONGKEWEI));
    assert(agnss_stream_workspace_buffer(AGNSS_STREAM_OWNER_ZHONGKEWEI,
                                         NULL) == NULL);
    agnss_stream_workspace_release(AGNSS_STREAM_OWNER_ZHONGKEWEI);
    assert(!agnss_stream_workspace_try_acquire(AGNSS_STREAM_OWNER_ZHONGKEWEI));
    agnss_stream_workspace_release(AGNSS_STREAM_OWNER_HUADA);
    assert(agnss_stream_workspace_try_acquire(AGNSS_STREAM_OWNER_ZHONGKEWEI));
    agnss_stream_workspace_release(AGNSS_STREAM_OWNER_ZHONGKEWEI);

    assert(service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_AGNSS));
    assert(service_workspace_buffer(&capacity) != NULL);
    assert(capacity >= 1024U);
    assert(!service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_OTA));
    assert(!service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_DIAGNOSTIC));
    service_workspace_release(SERVICE_WORKSPACE_OWNER_OTA);
    assert(!service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_OTA));
    service_workspace_release(SERVICE_WORKSPACE_OWNER_AGNSS);
    assert(service_workspace_try_acquire(SERVICE_WORKSPACE_OWNER_OTA));
    service_workspace_release(SERVICE_WORKSPACE_OWNER_OTA);

    /* RAM-03: a retained vendor half-frame survives service scratch reuse.
     * Exercise the full allocations, including their final bytes, for both
     * vendors and every service owner. Pointer inequality alone misses a
     * partially overlapping allocation. */
    for (int vendor = AGNSS_STREAM_OWNER_HUADA;
         vendor <= AGNSS_STREAM_OWNER_ZHONGKEWEI; ++vendor) {
        agnss_stream_owner_t owner = (agnss_stream_owner_t)vendor;
        size_t stream_capacity;
        assert(agnss_stream_workspace_try_acquire(owner));
        uint8_t *stream = agnss_stream_workspace_buffer(owner, &stream_capacity);
        assert(stream_capacity == 4096U);
        assert(!agnss_stream_workspace_try_acquire(owner));
        for (int service = SERVICE_WORKSPACE_OWNER_OTA;
             service <= SERVICE_WORKSPACE_OWNER_AGNSS; ++service) {
            service_workspace_owner_t scratch_owner = (service_workspace_owner_t)service;
            assert(service_workspace_try_acquire(scratch_owner));
            uint8_t *scratch = service_workspace_buffer(&capacity);
            assert(capacity == 1024U);
            assert(!service_workspace_try_acquire(scratch_owner));
            memset(stream, 0xA5, stream_capacity);
            memset(scratch, 0x5A, capacity);
            for (size_t i = 0; i < stream_capacity; ++i) assert(stream[i] == 0xA5);
            memset(stream, 0x3C, stream_capacity);
            for (size_t i = 0; i < capacity; ++i) assert(scratch[i] == 0x5A);
            service_workspace_release(scratch_owner);
            for (size_t i = 0; i < stream_capacity; ++i) assert(stream[i] == 0x3C);
        }
        agnss_stream_workspace_release(owner);
        agnss_stream_workspace_release(owner);
        assert(agnss_stream_workspace_buffer(owner, NULL) == NULL);
    }
    return 0;
}
'''


def main() -> None:
    cc = os.environ.get("CC") or shutil.which("gcc") or shutil.which("cc")
    if not cc:
        raise AssertionError("host C compiler is required")
    with tempfile.TemporaryDirectory(prefix="agnss_workspace_") as directory:
        temp = Path(directory)
        harness = temp / "harness.c"
        executable = temp / "harness.exe"
        harness.write_text(HARNESS, encoding="ascii")
        command = [
            cc, "-std=c99", "-Wall", "-Wextra", "-Werror",
            "-I", str(ROOT / "include"),
            str(harness),
            str(ROOT / "src" / "agnss_stream_workspace.c"),
            str(ROOT / "src" / "service_workspace.c"),
            "-o", str(executable),
        ]
        built = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        if built.returncode:
            raise AssertionError("workspace host build failed:\n" + built.stderr)
        run = subprocess.run([str(executable)], cwd=ROOT, capture_output=True, text=True)
        if run.returncode:
            raise AssertionError("workspace host run failed:\n" + run.stderr)
    print("test_agnss_workspace_ownership: PASS")


if __name__ == "__main__":
    main()
