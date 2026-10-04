"""Use the production Makefile and ARM tools to recover missing linked outputs."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
MAKE = os.environ.get("A300_MAKE") or shutil.which("make.exe") or str(
    ROOT.parent / "tools/w64devkit/w64devkit/bin/make.exe")
TOOLCHAIN = Path(os.environ.get("A300_TOOLCHAIN_DIR", ROOT / ".toolchain/bin"))


class BuildRecoveryTests(unittest.TestCase):
    def test_missing_peer_regenerates_bin_and_hex_serial_and_parallel(self):
        for missing in ("a300_firmware.map", "flash-build-profile.json", "stack-evidence.json",
                        "a300_firmware.elf.ltrans0.ltrans.su"):
            for jobs in (1, 4):
                with self.subTest(missing=missing, jobs=jobs), tempfile.TemporaryDirectory() as directory:
                    work = Path(directory)
                    (work / "tools").mkdir()
                    (work / "ldscript").mkdir()
                    (work / "include").mkdir()
                    shutil.copy2(ROOT / "include/build_version.h", work / "include/build_version.h")
                    shutil.copy2(ROOT / "Makefile", work / "Makefile")
                    for name in ("flash_capacity_guard.py", "flash_capacity_baseline.json", "map_ram_guard.py", "stack_usage_guard.py"):
                        shutil.copy2(ROOT / "tools" / name, work / "tools" / name)
                    shutil.copy2(ROOT / "ldscript/n32l406.ld", work / "ldscript/n32l406.ld")
                    source = work / "fixture.c"
                    text = ('__attribute__((used,section(".isr_vector"))) '
                            'const unsigned vectors[2]={0x20006000,0x08006009};\n'
                            'volatile unsigned fixture=0x11223344;\n'
                            'void Reset_Handler(void){for(;;)fixture++;}\n')
                    source.write_text(text)
                    cflags = "-mcpu=cortex-m4 -mthumb -Os -g0 -ffunction-sections -fdata-sections -flto=1 -flto-partition=one -fstack-usage"
                    # Freeze identity: only a missing linked peer, not the
                    # normal build timestamp refresh, may trigger recovery.
                    command = [MAKE, f"-j{jobs}", "-o", "include/build_version.h", "all", f"TOOLCHAIN_DIR={TOOLCHAIN.as_posix()}",
                               "C_SRCS=fixture.c", "ASM_SRCS=", f"CFLAGS={cflags}",
                               "LDFLAGS=-mcpu=cortex-m4 -mthumb -nostdlib -flto=1 -flto-partition=one -fstack-usage -Tldscript/n32l406.ld "
                               "-Wl,-Map=build/a300_firmware.map -Wl,--gc-sections"]

                    def run(cmd):
                        result = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=60)
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

                    run(command)
                    old = (work / "build/a300_firmware.bin").read_bytes()
                    # Same-size changed object, deliberately older timestamp:
                    # only the missing peer triggers relinking, not the source.
                    source.write_text(text.replace("11223344", "55667788"))
                    run([str(TOOLCHAIN / "arm-none-eabi-gcc.exe"), *cflags.split(),
                         "-c", "fixture.c", "-o", "build/fixture.o"])
                    old_time = (work / "build/a300_firmware.elf").stat().st_mtime - 10
                    os.utime(source, (old_time - 1, old_time - 1))
                    os.utime(work / "build/fixture.o", (old_time, old_time))
                    (work / "build" / missing).unlink()
                    run(command)
                    for extension, fmt in (("bin", "binary"), ("hex", "ihex")):
                        run([str(TOOLCHAIN / "arm-none-eabi-objcopy.exe"), "-O", fmt,
                             "build/a300_firmware.elf", f"expected.{extension}"])
                        self.assertEqual((work / f"build/a300_firmware.{extension}").read_bytes(),
                                         (work / f"expected.{extension}").read_bytes())
                    new = (work / "build/a300_firmware.bin").read_bytes()
                    self.assertEqual(len(old), len(new))
                    self.assertNotEqual(old, new)


if __name__ == "__main__":
    unittest.main()
