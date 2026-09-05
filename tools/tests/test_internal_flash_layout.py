from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


def macro(text: str, name: str) -> int:
    match = re.search(rf"^#define\s+{name}\s+(0x[0-9a-fA-F]+|\d+)(?:UL|U)?\b", text, re.M)
    assert match, f"missing {name}"
    return int(match.group(1), 0)


def memory_region(text: str, name: str) -> tuple[int, int]:
    match = re.search(
        rf"{name}\s*\([^)]*\)\s*:\s*ORIGIN\s*=\s*(0x[0-9a-fA-F]+),\s*LENGTH\s*=\s*(\d+)K",
        text,
    )
    assert match, f"missing {name} MEMORY region"
    return int(match.group(1), 16), int(match.group(2)) * 1024


def main() -> None:
    layout_path = ROOT / "include" / "firmware_layout.h"
    assert layout_path.exists(), "missing shared firmware_layout.h"
    layout = layout_path.read_text(encoding="utf-8")
    assert macro(layout, "FW_FLASH_BASE") == 0x08000000
    assert macro(layout, "FW_FLASH_END") == 0x08020000
    assert macro(layout, "BOOT_FLASH_BASE") == 0x08000000
    assert macro(layout, "BOOT_FLASH_SIZE") == 0x6000
    assert macro(layout, "APP_FLASH_BASE") == 0x08006000
    assert macro(layout, "APP_FLASH_SIZE") == 0x1A000
    assert macro(layout, "FW_SRAM_BASE") == 0x20000000
    assert macro(layout, "FW_SRAM_SIZE") == 0x6000

    boot = (ROOT / "bootloader" / "ldscript" / "n32l406_boot.ld").read_text()
    app = (ROOT / "ldscript" / "n32l406.ld").read_text()
    assert memory_region(boot, "FLASH") == (0x08000000, 24 * 1024)
    assert memory_region(boot, "RAM") == (0x20000000, 24 * 1024)
    assert memory_region(app, "FLASH") == (0x08006000, 104 * 1024)
    assert memory_region(app, "RAM") == (0x20000000, 24 * 1024)
    assert "0x08020000" in app and "ASSERT" in app
    assert "0x6000" in boot and "ASSERT" in boot

    main_c = (ROOT / "src" / "main.c").read_text(encoding="utf-8")
    hw_init = (ROOT / "src" / "hw_init.c").read_text(encoding="utf-8")
    assert main_c.index("hw_clock_init()") < main_c.index("hw_nvic_init()")
    assert hw_init.index("NVIC_SetVectorTable") < hw_init.index("SysTick_Config")
    assert "APP_FLASH_BASE - FW_FLASH_BASE" in hw_init
    syscalls = (ROOT / "src" / "syscalls.c").read_text(encoding="utf-8")
    assert "extern uint32_t _estack;" in main_c
    assert "extern uint32_t _estack;" in syscalls
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert 'if exist "$(BUILD)" rmdir /S /Q "$(BUILD)"' in makefile
    boot_makefile = (ROOT / "bootloader" / "Makefile").read_text(encoding="utf-8")
    assert "TOOLCHAIN_ROOT :=" in boot_makefile
    assert "CC := $(TOOLCHAIN_ROOT)/arm-none-eabi-gcc.exe" in boot_makefile
    assert 'if exist "build" rmdir /S /Q "build"' in boot_makefile
    assert "SDK_CFLAGS := -Wno-sign-compare -Wno-unused-parameter" in makefile
    assert "$(BUILD)/sdk/%.o: sdk/%.c" in makefile
    assert "PHDRS" in app and "text PT_LOAD FLAGS(5)" in app
    print("test_internal_flash_layout: PASS")


if __name__ == "__main__":
    main()
