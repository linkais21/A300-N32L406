"""Enforce N32L406CBL7 App/Bootloader Flash and static SRAM budgets."""
import re
import sys
import json
import hashlib
from pathlib import Path

from exception_stack_guard import assess_exception_stack

SRAM_BYTES = 24 * 1024
SRAM_BASE = 0x20000000
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


def hard_heap_reservation(map_text: str) -> tuple[int, int]:
    def symbol(name: str) -> int:
        matches = re.findall(
            rf"^\s*(0x[0-9a-fA-F]+)\s+(?:PROVIDE\s*\()?{name}\s*=",
            map_text, re.M,
        )
        if len(matches) != 1:
            raise ValueError(f"missing or duplicate {name} in final MAP")
        return int(matches[0], 16)

    end, limit = symbol("_end"), symbol("_heap_limit")
    if not SRAM_BASE <= end <= limit <= SRAM_BASE + SRAM_BYTES:
        raise ValueError("invalid hard heap reservation in final MAP")
    return end, limit

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
            heap_start, heap_limit = hard_heap_reservation(map_text)
            if heap_start - SRAM_BASE < ram:
                raise ValueError("static RAM exceeds linker data end")
            evidence = json.loads((path.parent / "stack-analysis.json").read_text(encoding="utf-8"))
            for file, field in ((path, "map_sha256"), (path.with_suffix(".elf"), "elf_sha256"),
                                (path.parent / "stack-evidence.json", "evidence_sha256")):
                if evidence.get(field) != hashlib.sha256(file.read_bytes()).hexdigest():
                    raise ValueError("stale stack evidence; run make ram-guard")
            known = evidence.get("known_main_frame_sum")
            if type(known) is not int or known < 0:
                raise ValueError("invalid stack evidence")
            heap_capacity = heap_limit - heap_start
            remaining = SRAM_BASE + SRAM_BYTES - heap_limit - known
            print(f"RAM diagnostic: static={ram} alignment={heap_start - SRAM_BASE - ram} "
                  f"hard_heap_reservation={heap_capacity} known_call_frames={known} "
                  f"remaining_after_heap={remaining} before_IRQ_unknowns "
                  f"required_gap={RUNTIME_GAP_BYTES}")
            if remaining < RUNTIME_GAP_BYTES:
                raise ValueError("known frames plus hard heap reservation breaches required runtime gap")
            if heap_capacity != 1024:
                raise ValueError("hard heap reservation changed")
            profile = json.loads((path.parent / "flash-build-profile.json").read_text(
                encoding="utf-8"))
            exception = assess_exception_stack(path.with_suffix(".elf"), evidence,
                                               profile, Path(__file__).resolve().parents[1])
            roots = evidence["roots"]
            stack = max(roots["main"]["known_frame_sum"],
                        roots["Reset_Handler"]["known_frame_sum"])
            if stack < known:
                raise ValueError("root stack sum contradicts main stack evidence")
            gap = SRAM_BASE + SRAM_BYTES - heap_limit - stack - exception["exception_stack_bytes"]
            if gap < RUNTIME_GAP_BYTES:
                raise ValueError(f"complete runtime gap {gap} < {RUNTIME_GAP_BYTES}")
            budget = {"schema_version": 1, "status": "pass",
                      "standalone_stack_report_status": evidence.get("status"),
                      "reviewed_execution_roots_status": "complete",
                      "elf_sha256": evidence["elf_sha256"],
                      "map_sha256": evidence["map_sha256"],
                      "stack_evidence_sha256": evidence["evidence_sha256"],
                      "static_sram": ram, "linker_alignment": heap_start - SRAM_BASE - ram,
                      "hard_heap_reservation": heap_capacity,
                      "boot_main_stack": stack, "exception": exception,
                      "runtime_gap": gap, "required_gap": RUNTIME_GAP_BYTES}
            (path.parent / "ram-budget.json").write_text(
                json.dumps(budget, indent=2) + "\n", encoding="utf-8")
            print(f"RAM guard PASS: static={ram} alignment={budget['linker_alignment']} "
                  f"heap={heap_capacity} boot_main_stack={stack} "
                  f"nested_exception={exception['exception_stack_bytes']} "
                  f"runtime_gap={gap}/{RUNTIME_GAP_BYTES}")
            return 0
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
