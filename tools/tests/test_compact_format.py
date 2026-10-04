"""Compare the firmware's bounded formatter with libc for used directives."""

from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
HARNESS = r'''
#include "a300_format.h"
#include <assert.h>
#include <limits.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

static void compare(size_t capacity, const char *format, ...)
{
    char actual[512], expected[512];
    va_list args, copy;
    memset(actual, 0x55, sizeof actual);
    memset(expected, 0x55, sizeof expected);
    va_start(args, format);
    va_copy(copy, args);
    int got = a300_vsnprintf(actual, capacity, format, args);
    int want = vsnprintf(expected, capacity, format, copy);
    va_end(copy);
    va_end(args);
    assert(got == want);
    assert(memcmp(actual, expected, sizeof actual) == 0);
}

int main(void)
{
    for (size_t capacity = 0; capacity < 40; ++capacity) {
        compare(capacity, "AT+QIRD=%u,%u", 3U, 1024U);
        compare(capacity, "GMTSET,%c%02u%02u", 'E', 8U, 4U);
        compare(capacity, "IP[%.*s:%u]", 7, "example.test", 9000U);
        compare(capacity, "%s,%.*s,%lu", "F39", 3, "abcdef", ULONG_MAX);
        compare(capacity, "%d|%u|%x|%X|%%", INT_MIN, UINT_MAX, 0xabcU, 0xabcU);
        compare(capacity, "GET %s HTTP/1.1\r\nHost: %s:%u\r\n", "/status", "example.test", 80U);
    }
    char output[16];
    assert(a300_snprintf(output, sizeof output, "%.2f", 1.0) == -1);
    assert(output[0] == '\0');
    assert(a300_snprintf(output, sizeof output, "%999999999999999999999u", 1U) == -1);
    assert(output[0] == '\0');
    assert(a300_snprintf(output, sizeof output, "%.999999999999999999999s", "a") == -1);
    assert(output[0] == '\0');
    puts("compact format equivalence: PASS");
    return 0;
}
'''


def main():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "format_harness.c"
        executable = root / "format_harness.exe"
        source.write_text(HARNESS, encoding="ascii")
        subprocess.run([
            "gcc", "-std=c99", "-Wall", "-Wextra", "-Werror", "-fno-builtin",
            "-I", str(ROOT / "include"), str(source), str(ROOT / "src/a300_format.c"),
            "-o", str(executable),
        ], check=True)
        subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    main()
