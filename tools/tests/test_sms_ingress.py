"""Compiles the production SMS ingress path without the MCU SDK."""
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CC = shutil.which("gcc") or shutil.which("cc")

def run():
    if not CC:
        raise SystemExit("test_sms_ingress: SKIP (no host C compiler)")
    source = r'''
      #include <assert.h>
      #include <stdint.h>
      #include <string.h>
      #include "sms_ingress.h"
      static unsigned count; static char last[192];
      static void sink(const char *from, const uint8_t *cmd, uint16_t len) {
        assert(!strcmp(from, "13800138000")); assert(len < sizeof(last)); memcpy(last, cmd, len); last[len]=0; ++count;
      }
      int main(void) {
        sms_ingress_set_callback(sink);
        sms_ingress_feed_line("+CMT: \"13800138000\",\"\",\"\""); sms_ingress_feed_line("IP=1");
        sms_ingress_feed_line("+CMT: \"13800138000\",\"\",\"\""); sms_ingress_feed_line("RELAY=ON");
        sms_ingress_feed_line("+CMT: \"13800138000\",\"\",\"\""); sms_ingress_feed_line("APN=net");
        sms_ingress_process(); assert(count==1 && !strcmp(last,"IP=1"));
        sms_ingress_process(); assert(count==2 && !strcmp(last,"RELAY=ON"));
        sms_ingress_feed_line("+CMT: \"13800138000\",\"\",\"\""); sms_ingress_feed_line("APN=net");
        sms_ingress_process(); assert(count==3 && !strcmp(last,"APN=net"));
        sms_ingress_feed_line("+CMT: \"13800138000\",\"\",\"\""); sms_ingress_feed_line("VIBSENS=1");
        sms_ingress_process(); assert(count==3); return 0;
      }
    '''
    with tempfile.TemporaryDirectory() as td:
        c = Path(td) / "sms_ingress_test.c"; exe = Path(td) / "sms_ingress_test.exe"; c.write_text(source)
        subprocess.run([CC, "-std=c99", "-Wall", "-Wextra", "-I", str(ROOT / "include"), str(c), str(ROOT / "src" / "sms_command.c"), str(ROOT / "src" / "sms_ingress.c"), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print("test_sms_ingress: PASS")

if __name__ == "__main__": run()
