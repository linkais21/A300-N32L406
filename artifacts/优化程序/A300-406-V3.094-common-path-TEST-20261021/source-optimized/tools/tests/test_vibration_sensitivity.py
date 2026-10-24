"""Compile the real product-level mapping; no changes to the hardware registers."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / "src/i2c_accel.c").read_text(encoding="utf-8")
defines = '\n'.join(re.findall(r'^#define\s+(?:VIB_THRESH|VIBRATION_\w+)\s+[^\n]+', source, re.M))
start = source.index('static uint16_t vibration_threshold_by_level(')
end = source.index('\n}', start) + 2
body = source[start:end]
test = r'''
int main(void) {
    assert(vibration_threshold_by_level(10) == 70);
    assert(vibration_threshold_by_level(15) == 90);
    assert(vibration_threshold_by_level(20) == 110);
    assert(vibration_threshold_by_level(0) == 90);
    assert(vibration_threshold_by_level(51) == 90);
    assert(vibration_threshold_by_level(255) == 90);
    for (unsigned level = 2; level <= 50; ++level)
        assert(vibration_threshold_by_level(level) > vibration_threshold_by_level(level-1));
    puts("PASS: 1..50 sensitivity mapping and default/fallback 15 (90 LSB)");
}
'''
with tempfile.TemporaryDirectory() as name:
    temp = Path(name)
    path = temp / 'mapping.c'
    path.write_text('#include <stdint.h>\n#include <assert.h>\n#include <stdio.h>\n' + defines + '\n' + body + '\n' + test)
    exe = temp / 'mapping.exe'
    subprocess.run([shutil.which('gcc'), '-std=c99', '-Wall', '-Wextra', '-Werror', str(path), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
