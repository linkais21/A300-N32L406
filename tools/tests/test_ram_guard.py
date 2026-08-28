from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "tools" / "map_ram_guard.py"

def run():
    good = ROOT / "tools" / "tests" / "fixtures_ram_good.map"
    bad = ROOT / "tools" / "tests" / "fixtures_ram_bad.map"
    good.write_text(".data 0x20000000 0x100\n.bss 0x20000100 0x100\n", encoding="ascii")
    bad.write_text(".data 0x20000000 0x5d00\n.bss 0x20005d00 0x100\n", encoding="ascii")
    try:
        assert subprocess.run([sys.executable, str(GUARD), str(good)], cwd=ROOT).returncode == 0
        assert subprocess.run([sys.executable, str(GUARD), str(bad)], cwd=ROOT).returncode != 0
    finally:
        good.unlink(missing_ok=True)
        bad.unlink(missing_ok=True)
    print("test_ram_guard: PASS")

if __name__ == "__main__": run()
