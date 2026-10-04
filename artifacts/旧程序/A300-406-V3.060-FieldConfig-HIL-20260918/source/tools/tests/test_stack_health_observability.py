from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = (ROOT / "src/main.c").read_text(encoding="utf-8")
SYSCALLS = (ROOT / "src/syscalls.c").read_text(encoding="utf-8")

assert "ram_watermark_measure" in MAIN
assert "sys_heap_break()" in MAIN
assert "HEAP_USED=%u STK_PEAK=%u RAM_GAP=%u RAM_AVAIL=%u F=%u" in MAIN
assert "STACK_MARGIN_MIN" in MAIN
assert "s_stack_margin_fault" in MAIN
assert "void *sys_heap_break(void)" in SYSCALLS
assert "const uint32_t *p = &_ebss;" not in MAIN

print("Stack health observability contract: PASS")
