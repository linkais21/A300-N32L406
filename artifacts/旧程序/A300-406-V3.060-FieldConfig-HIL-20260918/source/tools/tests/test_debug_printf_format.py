from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / "src/debug_uart.c").read_text(encoding="utf-8")
assert "int width = 0, zero_pad = 0;" in source
assert "case 'x':" in source and "print_uint_width" in source
assert "case 'u':" in source and "print_uint_width" in source
print("debug printf format contract: PASS")
