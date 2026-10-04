#!/usr/bin/env python3
"""STOP1 reconnect contract: reuse stored auth without forced registration."""

from pathlib import Path
import os
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]

HARNESS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include "jt808_session.h"

int main(void) {
    jt808_session_t s;
    jt808_session_init(&s, 0U);
    /* Initial STOP1 service window: stored auth selects AUTH directly. */
    jt808_session_sync_link(&s, true, 1U);
    assert(jt808_session_next_action(&s, true, 0U) == JT808_ACTION_AUTH);
    jt808_session_mark_sent(&s, JT808_ACTION_AUTH, 7U, 0U);
    jt808_session_mark_online(&s);
    assert(jt808_session_next_action(&s, true, 1U) == JT808_ACTION_NONE);

    /* Modem transport reconnects with a new generation.  Session state is
     * reset, but the caller's persisted auth remains available, so AUTH is
     * selected and REGISTER/0x0100 is never forced. */
    jt808_session_sync_link(&s, false, 1U);
    jt808_session_sync_link(&s, true, 2U);
    assert(jt808_session_next_action(&s, true, 2U) == JT808_ACTION_AUTH);

    /* A transient AUTH send failure is bounded and enters backoff; it cannot
     * create an unbounded 0x0102 loop during STOP1 service windows. */
    jt808_session_mark_send_failed(&s, JT808_ACTION_AUTH, 2U);
    jt808_session_mark_send_failed(&s, JT808_ACTION_AUTH, 5002U);
    jt808_session_mark_send_failed(&s, JT808_ACTION_AUTH, 10002U);
    assert(s.state == JT808_SESSION_BACKOFF);
    assert(jt808_session_next_action(&s, true, 10003U) == JT808_ACTION_NONE);
    return 0;
}
'''


def main() -> int:
    cc = os.environ.get("CC") or shutil.which("gcc") or shutil.which("cc")
    if not cc:
        print("stop1 reconnect auth contract: SKIP (compiler unavailable)")
        return 0
    with tempfile.TemporaryDirectory(prefix="stop1_reconnect_auth_") as d:
        d = Path(d)
        src = d / "harness.c"
        exe = d / "harness.exe"
        src.write_text(HARNESS, encoding="ascii")
        build = subprocess.run(
            [cc, "-std=c99", "-Wall", "-Wextra", "-Werror",
             "-I", str(ROOT / "include"), str(src),
             str(ROOT / "src" / "jt808_session.c"), "-o", str(exe)],
            cwd=ROOT, capture_output=True, text=True)
        if build.returncode:
            raise AssertionError("host build failed:\n" + build.stderr)
        run = subprocess.run([str(exe)], cwd=ROOT, capture_output=True,
                             text=True)
        if run.returncode:
            raise AssertionError("STOP1 reconnect auth contract failed:\n" +
                                 run.stderr)
    print("stop1 reconnect auth contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
