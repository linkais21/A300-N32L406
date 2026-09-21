import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]


HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>

#include "ram_watermark.h"

int main(void)
{
    uint32_t ram[64];
    ram_watermark_t result;
    size_t i;

    for (i = 0U; i < 64U; ++i) ram[i] = RAM_WATERMARK_PATTERN;

    /* Heap writes must not be counted as downward-growing stack use. */
    memset(&ram[0], 0x11, 8U * sizeof(ram[0]));
    assert(ram_watermark_measure(&ram[0], &ram[8], &ram[64], &result));
    assert(result.heap_used == 32U);
    assert(result.stack_peak == 0U);
    assert(result.free_gap == 224U);
    assert(result.total_available == 256U);

    /* Stack activity consumes the painted region from the top downward. */
    memset(&ram[60], 0x22, 4U * sizeof(ram[0]));
    assert(ram_watermark_measure(&ram[0], &ram[8], &ram[64], &result));
    assert(result.heap_used == 32U);
    assert(result.stack_peak == 16U);
    assert(result.free_gap == 208U);

    assert(!ram_watermark_measure(&ram[0], &ram[60], &ram[56], &result));
    assert(!ram_watermark_measure(&ram[8], &ram[4], &ram[64], &result));
    assert(!ram_watermark_measure(&ram[0], &ram[0], &ram[64], 0));
    return 0;
}
'''


def compiler() -> str:
    found = os.environ.get("CC") or shutil.which("gcc") or shutil.which("cc")
    if not found:
        raise AssertionError("host C compiler is required for RAM watermark test")
    return found


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="ram_watermark_") as directory:
        temp = Path(directory)
        harness = temp / "harness.c"
        executable = temp / "ram_watermark.exe"
        harness.write_text(HARNESS, encoding="ascii")
        command = [
            compiler(), "-std=c99", "-Wall", "-Wextra", "-Werror",
            "-I", str(ROOT / "include"), str(harness),
            str(ROOT / "src" / "ram_watermark.c"), "-o", str(executable),
        ]
        built = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        if built.returncode:
            raise AssertionError("RAM watermark host build failed:\n" + built.stderr)
        run = subprocess.run([str(executable)], cwd=ROOT, capture_output=True, text=True)
        if run.returncode:
            raise AssertionError("RAM watermark host test failed:\n" + run.stderr)
    print("RAM watermark measurement: PASS")


if __name__ == "__main__":
    main()
