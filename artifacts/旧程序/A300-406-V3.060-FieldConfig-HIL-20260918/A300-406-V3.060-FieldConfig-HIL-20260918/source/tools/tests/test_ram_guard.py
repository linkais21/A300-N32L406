from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "tools" / "map_ram_guard.py"

def run():
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "fixture.map"
        for mode, used, bss, expected in (
            ("app", 105776, 0x4578, 1),  # capacity alone cannot prove runtime safety
            ("app", 105776, 0x4579, 1),
            ("app", 106497, 0, 1),
            ("bootloader", 12312, 1, 0),
            ("bootloader", 12312, 0x4578, 0),
            ("bootloader", 12312, 0x4579, 1),
            ("bootloader", 24577, 0, 1),
        ):
            origin, capacity, region_capacity, symbol = (
                (0x08006000, 106496, 106496, "_app_load_end") if mode == "app"
                else (0x08000000, 24576, 22528, "_boot_end")
            )
            path.write_text(f"FLASH 0x{origin:x} 0x{region_capacity:x} xr\n"
                            f"  0x{origin+used:x} {symbol} = LOADADDR (.data) + SIZEOF (.data)\n"
                            f".data 0x20000000 0x100\n.bss 0x20000100 0x{bss:x}\n", encoding="ascii")
            result = subprocess.run([sys.executable, str(GUARD), mode, str(path)], cwd=ROOT,
                                    capture_output=True, text=True)
            assert result.returncode == expected, (mode, used, bss)
            if used > capacity:
                assert "Flash guard failed" in result.stdout, result.stdout
            elif mode == "app":
                assert "stack evidence" in result.stdout, result.stdout
    print("test_ram_guard: PASS")

if __name__ == "__main__": run()
