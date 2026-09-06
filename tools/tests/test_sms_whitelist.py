"""Host behavior tests for the bounded F39 SMS command ingress."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CC = shutil.which("gcc") or shutil.which("cc")


def run() -> None:
    if not CC:
        raise SystemExit("test_sms_whitelist: SKIP (no host C compiler)")
    source = r'''
        #include <assert.h>
        #include <stdint.h>
        #include <string.h>
        #include "sms_command.h"
        int main(void) {
          static const char *ok[] = {"PARAM?", "dualset=IP=1.2.3.4", "RESET", "PID:1", "IP=1", "FIP=1", "FREQ=1", "HBT=1", "MODEL=1", "SPEED=1", "APN=1", "RELAY=ON", "GPSDUP=1", "MLG=1", "CAR=1", "GPSBDS=1", "GMTSET=1", "VIBSENS=1", "DUALSET=VIBSENS=1"};
          static const char *bad[] = {"", "VIBSENSX=1", "RTKSW=ON", "PARAMETRIC=1", "IPX=1", "RELAYX=ON", "PARAM?junk", "DUALSET=IP?junk", "DUALSET=VIBSENSX=1", "DUALSET=IPX=1"};
          uint8_t cmd[SMS_COMMAND_MAX_LEN]; uint16_t len = 0;
          unsigned i;
          for (i = 0; i < sizeof(ok)/sizeof(ok[0]); ++i) assert(sms_command_allowed(ok[i]));
          for (i = 0; i < sizeof(bad)/sizeof(bad[0]); ++i) assert(!sms_command_allowed(bad[i]));
          sms_queue_reset();
          { uint8_t raw[] = {'I','P','=','1'}; assert(sms_queue_push("0", raw, 4)); }
          { uint8_t raw[] = {'I','P','X'}; assert(!sms_queue_push("0", raw, 3)); }
          sms_queue_reset();
          char phone[SMS_PHONE_MAX_LEN];
          assert(sms_queue_push("1", (const uint8_t *)"IP=1", 4));
          assert(sms_queue_push("2", (const uint8_t *)"RELAY=ON", 8));
          assert(!sms_queue_push("3", (const uint8_t *)"APN=1", 5));
          assert(sms_queue_pop(phone, sizeof(phone), cmd, sizeof(cmd), &len) && !strcmp(phone,"1") && len == 4 && !memcmp(cmd, "IP=1", 4));
          assert(sms_queue_pop(phone, sizeof(phone), cmd, sizeof(cmd), &len) && !strcmp(phone,"2") && len == 8 && !memcmp(cmd, "RELAY=ON", 8));
          assert(!sms_queue_pop(phone, sizeof(phone), cmd, sizeof(cmd), &len));
          memset(cmd, 'A', sizeof(cmd));
          assert(!sms_queue_push("1", cmd, SMS_COMMAND_MAX_LEN));
          assert(!sms_command_allowed("PARAM?junk"));
          return 0;
        }
    '''
    with tempfile.TemporaryDirectory() as td:
        cfile = Path(td) / "sms_test.c"
        exe = Path(td) / "sms_test.exe"
        cfile.write_text(source, encoding="utf-8")
        subprocess.run([CC, "-std=c99", "-Wall", "-Wextra", "-I", str(ROOT / "include"), str(cfile), str(ROOT / "src" / "sms_command.c"), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print("test_sms_whitelist: PASS")


if __name__ == "__main__":
    run()
