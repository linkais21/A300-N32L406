#!/usr/bin/env python3
"""Ensure the OTA state machine remains part of the ARM stack audit."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")
GUARD = (ROOT / "tools" / "stack_usage_guard.py").read_text(encoding="utf-8")


def main() -> int:
    assert "$(STACK_AUDIT_BUILD)/fota.o: src/fota.c" in MAKEFILE
    assert "$(STACK_AUDIT_BUILD)/fota.su" in MAKEFILE
    assert '"fota_process": 800' in GUARD
    print("test_fota_stack_guard: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
