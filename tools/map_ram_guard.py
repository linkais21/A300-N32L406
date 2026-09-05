"""Enforce N32L406CBL7 App/Bootloader Flash and static SRAM budgets."""
import re
import sys
from pathlib import Path

SRAM_BYTES = 24 * 1024
STACK_MARGIN_BYTES = 4096
RAM_LIMIT = SRAM_BYTES - STACK_MARGIN_BYTES
FLASH_LIMITS = {"app": 104 * 1024, "bootloader": 24 * 1024}
RAM_SECTION = re.compile(r"^\.(?:data|bss|noinit)\s+0x200[0-9a-fA-F]+\s+0x([0-9a-fA-F]+)")
FLASH_SECTION = re.compile(r"^\.(?:isr_vector|text|rodata|ARM(?:\.extab)?)\s+0x08[0-9a-fA-F]+\s+0x([0-9a-fA-F]+)")

def static_sram(map_text: str) -> int:
    return sum(int(match.group(1), 16) for line in map_text.splitlines() if (match := RAM_SECTION.match(line)))

def flash_used(map_text: str) -> int:
    return sum(int(match.group(1), 16) for line in map_text.splitlines() if (match := FLASH_SECTION.match(line)))

def run(mode: str, path: Path) -> int:
    if mode not in FLASH_LIMITS:
        print(f"unknown image mode: {mode}")
        return 1
    map_text = path.read_text(encoding="utf-8", errors="ignore")
    ram = static_sram(map_text)
    flash = flash_used(map_text)
    if ram > RAM_LIMIT:
        print(f"RAM guard failed: static={ram} limit={RAM_LIMIT} margin={STACK_MARGIN_BYTES}")
        return 1
    if flash > FLASH_LIMITS[mode]:
        print(f"Flash guard failed: mode={mode} used={flash} limit={FLASH_LIMITS[mode]}")
        return 1
    print(f"map guard PASS: mode={mode} flash={flash}/{FLASH_LIMITS[mode]} static_ram={ram}/{RAM_LIMIT}")
    return 0

if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: map_ram_guard.py <app|bootloader> <map>")
    raise SystemExit(run(sys.argv[1], Path(sys.argv[2])))
