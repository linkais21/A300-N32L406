"""Contracts preventing historical or interrupt-only vibration hits."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ACCEL = (ROOT / "src" / "i2c_accel.c").read_text(encoding="utf-8")
MAIN = (ROOT / "src" / "main.c").read_text(encoding="utf-8")


def function_body(source: str, signature: str) -> str:
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[brace + 1:index]
    raise AssertionError(f"unterminated function: {signature}")


vibration = function_body(ACCEL, "bool i2c_accel_vibration_hit")
work_mode_process = function_body(MAIN, "void work_mode_process")

assert "return s_diag.vibration_hit;" in vibration
assert "return true;" not in vibration, (
    "a historical episode must not convert a raw threshold miss into a hit"
)
assert "input.vibration_hit = true;" not in work_mode_process, (
    "the DA218E interrupt may wake sampling but cannot authorize realtime mode"
)
assert work_mode_process.count("++vibration_wake_samples;") == 1, (
    "each eligible accelerometer sample must be counted exactly once"
)

print("i2c accel vibration filter: PASS")
