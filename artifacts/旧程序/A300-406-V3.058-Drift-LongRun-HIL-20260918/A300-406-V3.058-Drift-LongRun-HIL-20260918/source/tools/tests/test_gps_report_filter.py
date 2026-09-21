"""G452 report filter regression, compiled against the actual L406 module."""
from pathlib import Path
import shutil, subprocess, tempfile
ROOT = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory() as tmp:
    d = Path(tmp)
    (d / "n32l40x.h").write_text("#include <stdint.h>\n")
    exe = d / "filter.exe"
    subprocess.run([shutil.which("gcc"), "-std=c99", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=undefined", "-fsanitize-undefined-trap-on-error",
                    "-I", str(d), "-I", str(ROOT / "include"),
                    str(ROOT / "tools/tests/gps_report_filter_host.c"),
                    str(ROOT / "src/gps_report_filter.c"), "-lm", "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
