from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "tools" / "map_ram_guard.py"

def run():
    good = ROOT / "tools" / "tests" / "fixtures_guard_good.map"
    ram_bad = ROOT / "tools" / "tests" / "fixtures_guard_ram_bad.map"
    app_bad = ROOT / "tools" / "tests" / "fixtures_guard_app_bad.map"
    boot_bad = ROOT / "tools" / "tests" / "fixtures_guard_boot_bad.map"
    good.write_text(".text 0x08006000 0x19fff\n.data 0x20000000 0x100\n.bss 0x20000100 0x4f00\n", encoding="ascii")
    ram_bad.write_text(".text 0x08006000 0x100\n.data 0x20000000 0x100\n.bss 0x20000100 0x4f01\n", encoding="ascii")
    app_bad.write_text(".text 0x08006000 0x1a001\n", encoding="ascii")
    boot_bad.write_text(".text 0x08000000 0x6001\n", encoding="ascii")
    try:
        assert subprocess.run([sys.executable, str(GUARD), "app", str(good)], cwd=ROOT).returncode == 0
        assert subprocess.run([sys.executable, str(GUARD), "app", str(ram_bad)], cwd=ROOT).returncode != 0
        assert subprocess.run([sys.executable, str(GUARD), "app", str(app_bad)], cwd=ROOT).returncode != 0
        assert subprocess.run([sys.executable, str(GUARD), "bootloader", str(boot_bad)], cwd=ROOT).returncode != 0
    finally:
        for path in (good, ram_bad, app_bad, boot_bad):
            path.unlink(missing_ok=True)
    print("test_ram_guard: PASS")

if __name__ == "__main__": run()
