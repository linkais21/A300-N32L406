"""Regression test: immediate send failures must consume retry budget."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

HARNESS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include "jt808_session.h"

int main(void) {
    jt808_session_t s;
    jt808_session_init(&s, 3U);
    jt808_session_sync_link(&s, true, 1U);
    assert(jt808_session_next_action(&s, true, 0U) == JT808_ACTION_AUTH);
    jt808_session_mark_send_failed(&s, JT808_ACTION_AUTH, 0U);
    assert(s.attempts == 1U);
    assert(jt808_session_next_action(&s, true, 4999U) == JT808_ACTION_NONE);
    jt808_session_mark_send_failed(&s, JT808_ACTION_AUTH, 5000U);
    assert(s.attempts == 2U);
    jt808_session_mark_send_failed(&s, JT808_ACTION_AUTH, 10000U);
    assert(s.attempts == 3U);
    jt808_session_mark_send_failed(&s, JT808_ACTION_AUTH, 15000U);
    assert(s.state == JT808_SESSION_BACKOFF);
    assert(s.attempts == 3U);
    jt808_session_sync_link(&s, true, 1U);
    assert(s.state == JT808_SESSION_BACKOFF);
    assert(jt808_session_next_action(&s, true, 69999U) == JT808_ACTION_NONE);
    assert(jt808_session_next_action(&s, true, 70000U) == JT808_ACTION_AUTH);
    jt808_session_mark_send_failed(&s, JT808_ACTION_AUTH, 70000U);
    assert(s.attempts == 1U);
    assert(s.state == JT808_SESSION_AUTHENTICATING);
    return 0;
}
'''


def main() -> int:
    cc = os.environ.get("CC") or shutil.which("gcc") or shutil.which("cc")
    if not cc:
        print("test_jt808_session_send_failure: SKIP (compiler unavailable)")
        return 0
    with tempfile.TemporaryDirectory(prefix="jt808_session_failure_") as d:
        d = Path(d)
        h = d / "harness.c"
        exe = d / "harness.exe"
        h.write_text(HARNESS, encoding="ascii")
        cmd = [cc, "-std=c99", "-Wall", "-Wextra", "-Werror",
               "-I", str(ROOT / "include"), str(h),
               str(ROOT / "src" / "jt808_session.c"), "-o", str(exe)]
        build = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        if build.returncode:
            raise AssertionError("host build failed:\n" + build.stderr)
        run = subprocess.run([str(exe)], cwd=ROOT, capture_output=True, text=True)
        if run.returncode:
            raise AssertionError("send-failure retry test failed:\n" + run.stderr)
    print("jt808 session send-failure retry: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
