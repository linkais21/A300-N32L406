"""Fail a release when static SRAM leaves less than the stack margin."""
import re
import sys
from pathlib import Path

SRAM_BYTES = 24 * 1024
STACK_MARGIN_BYTES = 4096
LIMIT = SRAM_BYTES - STACK_MARGIN_BYTES
SECTION = re.compile(r"^\.(?:data|bss|noinit)\s+0x200[0-9a-fA-F]+\s+0x([0-9a-fA-F]+)")

def static_sram(map_text: str) -> int:
    return sum(int(match.group(1), 16) for line in map_text.splitlines() if (match := SECTION.match(line)))

def run(path: Path) -> int:
    used = static_sram(path.read_text(encoding="utf-8", errors="ignore"))
    if used > LIMIT:
        print(f"RAM guard failed: static={used} limit={LIMIT} margin={STACK_MARGIN_BYTES}")
        return 1
    print(f"RAM guard PASS: static={used} limit={LIMIT} stack_margin={STACK_MARGIN_BYTES}")
    return 0

if __name__ == "__main__":
    raise SystemExit(run(Path(sys.argv[1])))
