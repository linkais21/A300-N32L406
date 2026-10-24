"""Verify the compile-time verbose log switch and its side-effect contract."""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    header = (ROOT / "include/debug_uart.h").read_text(encoding="utf-8")
    jt808 = (ROOT / "src/jt808.c").read_text(encoding="utf-8")
    mileage = (ROOT / "src/mileage.c").read_text(encoding="utf-8")
    assert "DBG_LOG_LEVEL_VERBOSE 2" in header
    assert "static inline int dbg_printf_verbose" in header
    assert jt808.count("DBG_PRINTF_VERBOSE(") == 4  # fallback + 3 calls
    assert mileage.count("DBG_PRINTF_VERBOSE(") == 2  # fallback + 1 call
    assert "trial_discard_trace" not in jt808 + mileage

    cc = shutil.which("gcc") or shutil.which("clang")
    assert cc, "a host C compiler is required"
    with tempfile.TemporaryDirectory(prefix="debug_log_levels_") as td:
        p = Path(td)
        (p / "test.c").write_text(
            '#include <assert.h>\n'
            '#include "debug_uart.h"\n'
            'static int side_effect;\n'
            'static int next_value(void) { ++side_effect; return side_effect; }\n'
            'int dbg_printf(const char *fmt, ...) { (void)fmt; return 0; }\n'
            'int main(void) {\n'
            '  dbg_printf_verbose("%d", next_value());\n'
            '  assert(side_effect == 1);\n'
            '  return 0;\n'
            '}\n',
            encoding="ascii",
        )
        exe = p / "test.exe"
        subprocess.run(
            [cc, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
             "-I", str(ROOT / "include"), str(p / "test.c"), "-o", str(exe)],
            check=True, timeout=60,
        )
        subprocess.run([str(exe)], check=True, timeout=10)
    print("debug log levels: PASS")


if __name__ == "__main__":
    main()
