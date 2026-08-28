"""Host harness for the final bounded SMS validation primitive."""
import shutil, subprocess, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
CC = shutil.which("gcc") or shutil.which("cc")
def run():
    if not CC: raise SystemExit("test_sms_execute_boundary: SKIP (no host C compiler)")
    src = '''#include <assert.h>\n#include <string.h>\n#include "sms_command.h"\nint main(void){char out[SMS_COMMAND_MAX_LEN]; assert(!sms_command_copy_allowed((const unsigned char*)"VIBSENS=1",9,out,sizeof(out))); assert(!sms_command_copy_allowed((const unsigned char*)"PARAM?junk",10,out,sizeof(out))); assert(sms_command_copy_allowed((const unsigned char*)"IP=1",4,out,sizeof(out))&&!strcmp(out,"IP=1")); return 0;}'''
    with tempfile.TemporaryDirectory() as td:
        c=Path(td)/"t.c"; exe=Path(td)/"t.exe"; c.write_text(src)
        subprocess.run([CC,"-std=c99","-Wall","-Wextra","-I",str(ROOT/"include"),str(c),str(ROOT/"src"/"sms_command.c"),"-o",str(exe)],check=True)
        subprocess.run([str(exe)],check=True)
    print("test_sms_execute_boundary: PASS")
if __name__ == "__main__": run()
