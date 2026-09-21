"""Execute production _sbrk with a simulated linker-owned RAM region."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HARNESS = r'''
#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <stdint.h>
#include <string.h>
#include "syscalls.h"
static uint32_t ram[512];
char *test_start_ptr = (char *)&ram[16];
char *test_limit_ptr = (char *)&ram[272];
uint32_t *test_stack_ptr = &ram[512];
void *_sbrk(int incr);
static void rejected(int incr) {
    void *before = sys_heap_break();
    errno = 0;
    assert(_sbrk(incr) == (void *)-1);
    assert(errno == ENOMEM);
    assert(sys_heap_break() == before);
}
int main(int argc, char **argv) {
    (void)argc;
    memset(ram, 0xa5, sizeof(ram));
    assert(sys_heap_break() == test_start_ptr);
    assert(_sbrk(0) == test_start_ptr);
    if (argv[1][0] == 'u') {
        assert(_sbrk(1024) == test_start_ptr);
        assert(sys_heap_break() == test_limit_ptr);
        rejected(1);
        rejected(INT_MAX);
        assert(_sbrk(-1024) == test_limit_ptr);
    } else if (argv[1][0] == 'l') {
        rejected(-1);
        rejected(INT_MIN);
    } else {
        assert(_sbrk(1) == test_start_ptr);
        assert(_sbrk(7) == test_start_ptr + 1);
        rejected(-9);
        rejected(INT_MIN);
        rejected(INT_MAX);
        assert(_sbrk(-8) == test_start_ptr + 8);
        for (int i = 0; i < 3; ++i) {
            assert(_sbrk(1024) == test_start_ptr);
            rejected(1);
            assert(_sbrk(-1024) == test_limit_ptr);
        }
    }
    assert(sys_heap_break() == test_start_ptr);
    for (unsigned i = 0; i < 512; ++i) assert(ram[i] == 0xa5a5a5a5U);
    return 0;
}
'''


def test_heap_bounds():
    cc = os.environ.get("CC") or shutil.which("gcc") or shutil.which("cc")
    assert cc, "host C compiler required"
    with tempfile.TemporaryDirectory(prefix="heap_bounds_") as directory:
        temp = Path(directory)
        harness = temp / "harness.c"
        fixture = temp / "linker_fixture.h"
        harness.write_text(HARNESS, encoding="ascii")
        # Only linker addresses are substituted; production arithmetic and errno
        # handling are compiled unchanged. Rename stubs to avoid host CRT hooks.
        fixture.write_text("\n".join([
            "#include <sys/stat.h>",
            "#include <stdlib.h>",
            "#include <stddef.h>",
            "#undef _fstat",
            "#define _end (*test_start_ptr)",
            "#define _heap_limit (*test_limit_ptr)",
            "#define _estack (*test_stack_ptr)",
        ] + [f"#define {name} test{name}" for name in (
            "_write", "_read", "_close", "_fstat", "_isatty", "_lseek",
            "_getpid", "_kill", "_exit")]), encoding="ascii")
        exe = temp / "heap.exe"
        subprocess.run([cc, "-std=c99", "-Wall", "-Wextra", "-Werror",
                        "-D_DEFAULT_SOURCE", "-include", str(fixture),
                        "-I", str(ROOT / "include"), str(harness),
                        str(ROOT / "src/syscalls.c"), "-o", str(exe)], check=True)
        failures = []
        for case in ("upper", "lower", "mixed"):
            result = subprocess.run([str(exe), case], capture_output=True, text=True)
            if result.returncode:
                failures.append(case + ": " + result.stderr)
        assert not failures, "\n".join(failures)


if __name__ == "__main__":
    test_heap_bounds()
    print("heap bounds: PASS (upper, lower, mixed, failure recovery)")
