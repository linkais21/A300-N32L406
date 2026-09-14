#!/usr/bin/env python3
"""Ensure builds and releases use final LTO evidence, including signature TUs."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")
GUARD = (ROOT / "tools" / "stack_usage_guard.py").read_text(encoding="utf-8")
BUILDER = (ROOT / "tools" / "build_dev_release.py").read_text(encoding="utf-8")


def main() -> int:
    assert "STACK_AUDIT_CFLAGS" not in MAKEFILE
    assert "-flto=1 -flto-partition=one -fstack-usage" in MAKEFILE
    assert "$(TARGET).elf.ltrans0.ltrans.su" in MAKEFILE
    assert "$(BUILD)/src/firmware_signature.o $(BUILD)/third_party/micro-ecc/uECC.o" in MAKEFILE
    assert "ram-guard: stack-report" in MAKEFILE
    assert "stack-guard: ram-guard" in MAKEFILE
    assert BUILDER.index('"release-gate"') < BUILDER.index('package=out/')
    assert "AUDITED_STACK_BYTES" not in (ROOT / "tools/map_ram_guard.py").read_text()
    print("test_fota_stack_guard: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
