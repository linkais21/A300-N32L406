from pathlib import Path
import os
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")
MAIN = (ROOT / "src/main.c").read_text(encoding="utf-8")
MANAGER = (ROOT / "src/agnss_manager.c").read_text(encoding="utf-8")

assert "$(EXTRA_CFLAGS)" in MAKEFILE
assert "#ifndef A300_HARDWARE_BRINGUP" not in MAIN
assert "#ifdef A300_HARDWARE_BRINGUP" in MANAGER
assert "voidagnss_process(void){}" in "".join(MANAGER.split())
assert "voidagnss_init(gnss_type_tt){(void)t;}" in "".join(MANAGER.split())
assert "#else" in MANAGER and "#endif" in MANAGER
assert "#ifdef A300_HARDWARE_BRINGUP" in (ROOT / "src/agnss_huada.c").read_text(encoding="utf-8")


def make_value(*args: str) -> str:
    make = shutil.which("make") or shutil.which("mingw32-make") or os.environ.get("A300_MAKE")
    if make is None:
        candidate = Path(r"D:\ST\STM32CubeIDE_2.1.1\STM32CubeIDE\plugins\com.st.stm32cube.ide.mcu.externaltools.make.win32_2.2.100.202601091506\tools\bin\make.exe")
        make = str(candidate) if candidate.is_file() else None
    assert make is not None, "GNU Make is required for the profile contract"
    result = subprocess.run(
        [make, "--no-print-directory", "-s", *args, "print-profile"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.replace("\\", "/")


normal = make_value()
hil = make_value("EXTRA_CFLAGS=-DA300_HARDWARE_BRINGUP")

assert "BUILD=build\n" in normal
assert "agnss_storage.c" in normal and "agnss_zhongkewei.c" not in normal
assert "BUILD=build-hardware-bringup\n" in hil
assert "agnss_storage.c" not in hil and "agnss_zhongkewei.c" not in hil
assert "agnss_manager.c" in hil and "agnss_huada.c" in hil

print("Hardware bring-up profile contract: PASS")
