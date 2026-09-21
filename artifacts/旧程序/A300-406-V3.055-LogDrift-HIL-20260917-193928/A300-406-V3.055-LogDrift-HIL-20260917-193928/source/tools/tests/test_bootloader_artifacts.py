from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_bootloader_all_builds_flashable_hex_and_bin_artifacts():
    makefile = (ROOT / "bootloader" / "Makefile").read_text(encoding="utf-8")

    assert "all: build/bootloader.hex build/bootloader.bin" in makefile
    assert "build/bootloader.hex: build/bootloader.elf" in makefile
    assert "build/bootloader.bin: build/bootloader.elf" in makefile
    assert "$(OBJCOPY) -O ihex $< $@" in makefile
    assert "$(OBJCOPY) -O binary $< $@" in makefile


if __name__ == "__main__":
    test_bootloader_all_builds_flashable_hex_and_bin_artifacts()
    print("test_bootloader_artifacts: PASS")
