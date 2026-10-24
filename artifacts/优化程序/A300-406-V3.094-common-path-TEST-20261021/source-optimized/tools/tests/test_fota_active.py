"""Exercise the shared OTA ownership query against every declared state."""
import re
import subprocess
import tempfile
from pathlib import Path

from test_tcp_manager_fip import compiler

ROOT = Path(__file__).resolve().parents[2]


def test_fota_active():
    cc = compiler()
    assert cc, "host C compiler required"
    expected = {
        "IDLE": False, "CONNECTING": True, "DOWNLOADING": True,
        "VERIFYING": True, "READY": True, "ERROR": False,
        "CHECK_CONNECTING": True, "CHECKING": True, "PREPARING": True,
    }
    header = (ROOT / "include/fota.h").read_text(encoding="utf-8")
    assert set(re.findall(r"\bFOTA_STATE_([A-Z_]+)\b", header)) == set(expected), \
        "Update the ownership contract when adding an OTA state"
    cases = "\n".join(
        f"state = FOTA_STATE_{name}; check({int(active)});"
        for name, active in expected.items()
    )
    with tempfile.TemporaryDirectory(prefix="fota_active_") as directory:
        source = Path(directory) / "active.c"
        binary = Path(directory) / "active.exe"
        source.write_text('''
#include <assert.h>
#include "fota.h"
static fota_state_t state;
static unsigned reads;
fota_state_t fota_get_state(void) { ++reads; return state; }
static void check(bool expected) {
    reads = 0;
    assert(fota_is_active() == expected);
    assert(reads == 1);
}
int main(void) {
''' + cases + '''
    state = (fota_state_t)255; check(false);
    state = (fota_state_t)-1; check(false);
    return 0;
}
''', encoding="ascii")
        subprocess.run([cc, "-std=c99", "-Wall", "-Wextra", "-Werror",
                        "-I", str(ROOT / "include"), str(source), "-o", str(binary)],
                       check=True)
        subprocess.run([str(binary)], check=True)


if __name__ == "__main__":
    test_fota_active()
    print("test_fota_active: PASS")
