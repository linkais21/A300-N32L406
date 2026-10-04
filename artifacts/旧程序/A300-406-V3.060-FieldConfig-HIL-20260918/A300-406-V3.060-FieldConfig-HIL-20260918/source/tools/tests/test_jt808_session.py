#!/usr/bin/env python3
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]

HARNESS = r'''
#include <assert.h>
#include "jt808_session.h"

static void send_attempt(jt808_session_t *session,
                         jt808_session_action_t action,
                         uint16_t serial, uint32_t now)
{
    jt808_session_mark_sent(session, action, serial, now);
    assert(session->pending_valid);
    assert(session->pending_serial == serial);
}

int main(void)
{
    jt808_session_t main_session;
    jt808_session_t backup_session;

    jt808_session_init(&main_session, 0U);
    jt808_session_init(&backup_session, 3U);
    jt808_session_sync_link(&main_session, true, 1U);
    jt808_session_sync_link(&backup_session, true, 9U);

    assert(jt808_session_next_action(&main_session, false, 0U) == JT808_ACTION_REGISTER);
    assert(jt808_session_next_action(&backup_session, true, 0U) == JT808_ACTION_AUTH);

    jt808_session_mark_send_failed(&backup_session, JT808_ACTION_AUTH, 10U);
    assert(backup_session.attempts == 1U && !backup_session.pending_valid);
    assert(jt808_session_next_action(&backup_session, true, 5009U) == JT808_ACTION_NONE);
    assert(jt808_session_next_action(&backup_session, true, 5010U) == JT808_ACTION_AUTH);

    send_attempt(&main_session, JT808_ACTION_REGISTER, 7U, 100U);
    assert(main_session.attempts == 1U);
    assert(jt808_session_next_action(&main_session, false, 5099U) == JT808_ACTION_NONE);
    assert(jt808_session_next_action(&main_session, false, 5100U) == JT808_ACTION_REGISTER);
    assert(!jt808_session_accept_register(&main_session, 2U, 7U));
    assert(!jt808_session_accept_register(&main_session, 1U, 8U));
    assert(jt808_session_accept_register(&main_session, 1U, 7U));

    send_attempt(&main_session, JT808_ACTION_AUTH, 70U, 200U);
    assert(main_session.attempts == 1U);
    assert(jt808_session_accept_auth(&main_session, 1U, 70U));
    assert(!jt808_session_reject_or_timeout(&main_session, 200U));
    assert(!jt808_session_accept_auth(&main_session, 1U, 70U));
    assert(jt808_session_next_action(&main_session, true, 5199U) == JT808_ACTION_NONE);
    assert(jt808_session_next_action(&main_session, true, 5200U) == JT808_ACTION_AUTH);

    send_attempt(&main_session, JT808_ACTION_AUTH, 8U, 5200U);
    send_attempt(&main_session, JT808_ACTION_AUTH, 9U, 10200U);
    assert(main_session.attempts == 3U);
    assert(jt808_session_next_action(&main_session, true, 15200U) == JT808_ACTION_NONE);
    assert(jt808_session_reject_or_timeout(&main_session, 15200U));
    assert(main_session.state == JT808_SESSION_BACKOFF);
    assert(jt808_session_next_action(&main_session, false, 75199U) == JT808_ACTION_NONE);
    assert(jt808_session_next_action(&main_session, false, 75200U) == JT808_ACTION_REGISTER);
    jt808_session_mark_send_failed(&main_session, JT808_ACTION_REGISTER, 75200U);
    assert(main_session.attempts == 1U && !main_session.pending_valid);
    assert(jt808_session_next_action(&main_session, false, 80199U) == JT808_ACTION_NONE);
    assert(jt808_session_next_action(&main_session, false, 80200U) == JT808_ACTION_REGISTER);

    send_attempt(&backup_session, JT808_ACTION_AUTH, 20U, 200U);
    assert(jt808_session_accept_auth(&backup_session, 9U, 20U));
    jt808_session_mark_online(&backup_session);
    assert(backup_session.state == JT808_SESSION_ONLINE);
    assert(backup_session.waiting_first_fix);

    jt808_session_sync_link(&main_session, false, 1U);
    assert(main_session.state == JT808_SESSION_IDLE && !main_session.pending_valid);
    assert(backup_session.state == JT808_SESSION_ONLINE);

    jt808_session_sync_link(&backup_session, true, 10U);
    assert(backup_session.state == JT808_SESSION_IDLE);
    assert(!jt808_session_accept_auth(&backup_session, 9U, 20U));

    return 0;
}
'''

def compiler():
    cc = os.environ.get("CC") or shutil.which("gcc") or shutil.which("clang") or shutil.which("cc")
    if cc:
        return cc
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if "WinLibs" in directory:
            return str(Path(directory.strip('"')) / "gcc.exe")
    return None

def main() -> int:
    cc = compiler()
    if cc is None:
        print("test_jt808_session: FAIL (host C compiler required)")
        return 1
    with tempfile.TemporaryDirectory(prefix="jt808_session_") as directory:
        temp = Path(directory)
        harness = temp / "harness.c"
        binary = temp / "jt808_session.exe"
        harness.write_text(HARNESS, encoding="ascii")
        command = [cc, "-std=c99", "-Wall", "-Wextra", "-Werror",
                   "-I", str(ROOT / "include"), str(harness),
                   str(ROOT / "src" / "jt808_session.c"), "-o", str(binary)]
        build = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        if build.returncode:
            print(build.stdout + build.stderr, end="")
            return build.returncode
        run = subprocess.run([str(binary)], cwd=ROOT, capture_output=True, text=True)
        if run.returncode:
            print(run.stdout + run.stderr, end="")
            return run.returncode
    print("test_jt808_session: PASS")
    return 0

if __name__ == "__main__":
    sys.exit(main())
