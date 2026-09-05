"""Source contracts for the work-mode DA218E vibration adapter."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
HEADER = (ROOT / "include" / "i2c_accel.h").read_text(encoding="utf-8")
SOURCE = (ROOT / "src" / "i2c_accel.c").read_text(encoding="utf-8")
MAIN = (ROOT / "src" / "main.c").read_text(encoding="utf-8")


def require(pattern: str, text: str, message: str) -> None:
    if not re.search(pattern, text, re.MULTILINE | re.DOTALL):
        raise AssertionError(message)


def main() -> None:
    require(r"bool\s+i2c_accel_vibration_hit\s*\(\s*uint8_t\s+sensitivity_level\s*\)\s*;",
            HEADER, "missing bounded vibration-hit declaration")
    require(r"void\s+i2c_accel_reset_vibration_window\s*\(\s*void\s*\)\s*;",
            HEADER, "missing vibration-window reset declaration")
    require(r"const\s+accel_diag_t\s*\*\s*i2c_accel_get_diag\s*\(\s*void\s*\)\s*;",
            HEADER, "missing accelerometer diagnostic declaration")
    require(r"bool\s+i2c_accel_vibration_sample_due\s*\(\s*void\s*\)\s*;",
            HEADER, "missing vibration sample cadence declaration")
    require(r"void\s+i2c_accel_prepare_wake_sampling\s*\(\s*void\s*\)\s*;",
            HEADER, "missing STOP1 wake sampling reset declaration")
    require(r"void\s+i2c_accel_prepare_wake_sampling\s*\(\s*void\s*\)",
            SOURCE, "missing STOP1 wake sampling reset implementation")
    require(r"work_sleep_wake_t wake = work_mode_sleep_take_wake\(\).*?"
            r"i2c_accel_prepare_wake_sampling\s*\(\s*\)",
            MAIN, "wake sampling must be prepared before work-mode evaluation")
    require(r"last_delta|delta", HEADER, "diagnostic must expose vibration delta")
    require(r"\[ACCEL\].*X=%d.*Y=%d.*Z=%d.*read_ok=%u",
            MAIN, "missing accelerometer sample diagnostics")
    require(r"\[ACCEL\].*vibration.*X=%d.*Y=%d.*Z=%d",
            SOURCE, "missing vibration sample diagnostics")
    require(r"VIBRATION_SAMPLE_INTERVAL_MS\s+200U", SOURCE,
            "vibration adapter must retain the 200 ms sample cadence")
    require(r"vibration_threshold_by_level", SOURCE,
            "product sensitivity must use a named level-to-threshold mapping")
    require(r"VIBRATION_SENSITIVITY_LEVEL_10", SOURCE,
            "level 10 must be represented as a named product-level mapping")
    require(r"DA218E_REG_INT_SET1\s+0x16", SOURCE,
            "active-motion interrupt setup must use INT_SET1")
    require(r"DA218E_REG_INT_MAP1\s+0x19", SOURCE,
            "active-motion interrupt setup must use INT_MAP1")
    require(r"i2c_write_reg\(DA218E_REG_INT_CONFIG,\s*0x81U\).*?"
            r"i2c_write_reg\(DA218E_REG_INT_CONFIG,\s*0x01U\)", SOURCE,
            "INT_CONFIG must reset then enable edge interrupt mode")
    require(r"i2c_write_reg\(DA218E_REG_INT_LATCH,\s*0x00U\)", SOURCE,
            "INT_LATCH must be non-latching for repeatable wake edges")
    require(r"i2c_write_reg\(DA218E_REG_INT_SET1,\s*0x83U\)", SOURCE,
            "active-motion interrupt must enable reference and all axes")
    require(r"i2c_write_reg\(DA218E_REG_INT_MAP1,\s*0x04U\)", SOURCE,
            "active-motion interrupt must map to INT1")
    require(r"i2c_write_reg\(DA218E_REG_ACTIVE_THS,\s*0x26U\)", SOURCE,
            "active-motion threshold must match sensitivity level 10")
    require(r"bool\s+i2c_accel_vibration_hit\s*\([^)]*\)\s*\{.*?"
            r"if\s*\(\s*!i2c_accel_read\s*\(\s*&d\s*\)\s*\)\s*\{.*?"
            r"i2c_accel_reset_vibration_window\s*\(\s*\)\s*;\s*return\s+false\s*;",
            SOURCE, "a failed sample must reset the window and return no hit")
    print("i2c accel vibration adapter: PASS")


if __name__ == "__main__":
    main()
