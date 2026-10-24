"""Contract for the bounded 25-hour platform outage recovery."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / "src/main.c").read_text(encoding="utf-8-sig")
assert "PLATFORM_OFFLINE_RESET_S (25UL * 60UL * 60UL)" in source
assert "if (jt808_is_online())" in source
assert "NVIC_SystemReset();" in source
assert "blind_zone_recovery_process" in source
print("platform offline reset and blind-zone preservation: PASS")
