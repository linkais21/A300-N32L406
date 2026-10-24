"""The unsupported polygon command must retain its explicit failure reply."""
import subprocess
import tempfile
from pathlib import Path

from test_jt808_dual_session import compiler

ROOT = Path(__file__).resolve().parents[2]
HARNESS = r'''
#include <assert.h>
#include <stddef.h>
#include "geofence.h"
#include "jt808.h"
static unsigned replies;
static uint16_t expected_sn;
int jt808_send_general_resp(uint16_t sn, uint16_t id, uint8_t result)
{
    assert(sn == expected_sn);
    assert(id == 0x8604U);
    assert(result == 1U);
    ++replies;
    return -1; /* Failed transmission must not create an unbounded retry. */
}
int main(void)
{
    const uint8_t body[] = {0x00U, 0xffU};
    expected_sn = 0U;
    geofence_handle_jt808(NULL, 0U, expected_sn);
    expected_sn = 65535U;
    geofence_handle_jt808(body, sizeof(body), expected_sn);
    geofence_handle_jt808(body, sizeof(body), expected_sn);
    assert(replies == 3U);
    return 0;
}
'''


def main():
    cc = compiler()
    if not cc:
        raise RuntimeError("Host C compiler is required")
    with tempfile.TemporaryDirectory(prefix="geofence_rejection_") as directory:
        temp = Path(directory)
        harness, binary = temp / "test.c", temp / "test.exe"
        harness.write_text(HARNESS, encoding="ascii")
        subprocess.run([cc, "-std=c99", "-Wall", "-Wextra", "-Werror",
                        "-I", str(ROOT / "include"), str(harness),
                        str(ROOT / "src/geofence.c"), "-o", str(binary)],
                       check=True, timeout=60)
        subprocess.run([str(binary)], check=True, timeout=10)
    print("test_geofence_rejection: PASS")


if __name__ == "__main__":
    main()
