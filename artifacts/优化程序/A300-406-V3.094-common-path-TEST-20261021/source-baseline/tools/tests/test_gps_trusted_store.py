"""Regression contract for trusted GPS Flash sequence recovery."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "src/gps.c").read_text(encoding="utf-8-sig")

assert "static uint32_t s_trusted_store_sequence;" in SOURCE
assert "s_trusted_store_sequence = found ? seq : 0U;" in SOURCE
assert "r.sequence=++s_trusted_store_sequence" in SOURCE
assert "static uint32_t seq" not in SOURCE
print("gps trusted store sequence recovery: PASS")
