"""Compare production CRC32 against zlib, including incremental checkpoints."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[2]


def main():
    # Deterministic, nonuniform bytes cross page, sector and receive boundaries.
    data = bytes((i * 73 + (i >> 3) * 19) & 255 for i in range(8193))
    lengths = (0, 1, 7, 31, 32, 255, 256, 257, 4095, 4096, 4097, 8193)
    cases = ",\n".join(
        f"{{{n}U, 0x{zlib.crc32(data[:n]):08x}U}}" for n in lengths)
    seeds = (0, 1, 0x12345678, 0xFFFFFFFF)
    seeded = ",\n".join(
        f"{{0x{s:08x}U, 0x{(zlib.crc32(data, s ^ 0xFFFFFFFF) ^ 0xFFFFFFFF):08x}U}}"
        for s in seeds)
    source = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include "crc32.h"
static const struct { uint32_t length, expected; } cases[] = { CASES };
static const struct { uint32_t seed, expected; } seeds[] = { SEEDS };
int main(void) {
    uint8_t data[8193];
    const uint32_t chunks[] = {1U, 7U, 255U, 256U, 4096U};
    for (uint32_t i = 0; i < sizeof data; ++i)
        data[i] = (uint8_t)(i * 73U + (i >> 3) * 19U);
    assert(crc32_compute(NULL, 0) == 0U);
    assert(crc32_update(0x12345678U, NULL, 0) == 0x12345678U);
    assert(crc32_compute("123456789", 9) == 0xcbf43926U);
    for (unsigned i = 0; i < sizeof cases / sizeof cases[0]; ++i) {
        assert(crc32_compute(data, cases[i].length) == cases[i].expected);
        for (unsigned c = 0; c < sizeof chunks / sizeof chunks[0]; ++c) {
            uint32_t state = 0xffffffffU, offset = 0;
            while (offset < cases[i].length) {
                uint32_t n = cases[i].length - offset;
                if (n > chunks[c]) n = chunks[c];
                state = crc32_update(state, data + offset, n);
                offset += n;
            }
            assert((uint32_t)~state == cases[i].expected);
        }
    }
    for (unsigned i = 0; i < sizeof seeds / sizeof seeds[0]; ++i)
        assert(crc32_update(seeds[i].seed, data, sizeof data) == seeds[i].expected);
    return 0;
}
'''.replace("CASES", cases).replace("SEEDS", seeded)
    cc = shutil.which("gcc") or shutil.which("clang")
    assert cc, "Host C compiler is required"
    with tempfile.TemporaryDirectory(prefix="crc32_equivalence_") as directory:
        temp = Path(directory)
        harness, exe = temp / "test.c", temp / "test.exe"
        harness.write_text(source, encoding="ascii")
        subprocess.run([cc, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
                        "-I", str(ROOT / "include"), str(harness),
                        str(ROOT / "src/crc32.c"), "-o", str(exe)],
                       check=True, timeout=60)
        subprocess.run([str(exe)], check=True, timeout=10)
    print("CRC32 zlib/reference and incremental equivalence: PASS")


if __name__ == "__main__":
    main()
