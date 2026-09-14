"""Enforce N32L406CBL7 App/Bootloader Flash and static SRAM budgets."""
import re
import sys
import json
import hashlib
from pathlib import Path

SRAM_BYTES = 24 * 1024
RUNTIME_GAP_BYTES = 4096
# Preserve the pre-RAM-01 Boot regression ceiling; this is not a proven Boot
# stack bound. App now requires its own final-link evidence instead.
BOOT_STATIC_RAM_LIMIT = 18040
FLASH_LIMITS = {"app": 104 * 1024, "bootloader": 24 * 1024}
FLASH_REGION_LIMITS = {"app": 104 * 1024, "bootloader": 22 * 1024}
RAM_SECTION = re.compile(r"^\.(?:data|bss|noinit)\s+0x200[0-9a-fA-F]+\s+0x([0-9a-fA-F]+)")
FLASH_ORIGINS = {"app": 0x08006000, "bootloader": 0x08000000}
FLASH_END_SYMBOLS = {"app": "_app_load_end", "bootloader": "_boot_end"}

def static_sram(map_text: str) -> int:
    return sum(int(match.group(1), 16) for line in map_text.splitlines() if (match := RAM_SECTION.match(line)))

def flash_used(map_text: str, mode: str = "app") -> int:
    """Measure load-address span, including RAM initializers and alignment."""
    regions = re.findall(r"^FLASH\s+(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)\s", map_text, re.M)
    if len(regions) != 1 or tuple(int(v, 16) for v in regions[0]) != (
            FLASH_ORIGINS[mode], FLASH_REGION_LIMITS[mode]):
        raise ValueError("missing or unexpected FLASH memory region")
    ends = re.findall(r"^\s*(0x[0-9a-fA-F]+)\s+" + FLASH_END_SYMBOLS[mode] + r"\s*=", map_text, re.M)
    if len(ends) != 1:
        raise ValueError("missing or duplicate Flash load-end symbol")
    used = int(ends[0], 16) - FLASH_ORIGINS[mode]
    if used < 8:
        raise ValueError("invalid Flash load span")
    return used

def run(mode: str, path: Path) -> int:
    if mode not in FLASH_LIMITS:
        print(f"unknown image mode: {mode}")
        return 1
    try:
        map_text = path.read_text(encoding="utf-8")
        ram = static_sram(map_text)
        flash = flash_used(map_text, mode)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"map guard failed: {exc}")
        return 1
    static_limit = BOOT_STATIC_RAM_LIMIT if mode == "bootloader" else SRAM_BYTES
    if ram > static_limit:
        print(f"RAM guard failed: static={ram} limit={static_limit}")
        return 1
    if flash > FLASH_LIMITS[mode]:
        print(f"Flash guard failed: mode={mode} used={flash} limit={FLASH_LIMITS[mode]}")
        return 1
    if mode == "app":
        try:
            evidence = json.loads((path.parent / "stack-analysis.json").read_text(encoding="utf-8"))
            for file, field in ((path, "map_sha256"), (path.with_suffix(".elf"), "elf_sha256"),
                                (path.parent / "stack-evidence.json", "evidence_sha256")):
                if evidence.get(field) != hashlib.sha256(file.read_bytes()).hexdigest():
                    raise ValueError("stale stack evidence; run make ram-guard")
            known = evidence.get("known_main_frame_sum")
            if type(known) is not int or known < 0:
                raise ValueError("invalid stack evidence")
            remaining = SRAM_BYTES - ram - known
            print(f"RAM diagnostic: static={ram} known_call_frames={known} "
                  f"remaining_before_heap_IRQ_unknowns={remaining} required_gap={RUNTIME_GAP_BYTES}")
            if remaining < RUNTIME_GAP_BYTES:
                raise ValueError("known call-frame estimate already breaches required runtime gap")
            # RAM-01 deliberately removes the old unconditional 2440-byte
            # assertion. No reviewed complete budget is available yet.
            raise ValueError("incomplete stack evidence: " + evidence.get("error", "unproven runtime bound"))
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            print(f"RAM guard failed: stack evidence: {exc}")
            return 1
    print(f"map guard PASS (static capacity only): mode={mode} flash={flash}/{FLASH_LIMITS[mode]} "
          f"static_ram={ram}/{static_limit}; Boot runtime stack not audited")
    return 0

if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: map_ram_guard.py <app|bootloader> <map>")
    raise SystemExit(run(sys.argv[1], Path(sys.argv[2])))
