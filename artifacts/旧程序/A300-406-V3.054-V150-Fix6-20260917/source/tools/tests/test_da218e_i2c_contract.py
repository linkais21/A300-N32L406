from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = (ROOT / "include/config.h").read_text(encoding="utf-8")
DRIVER = (ROOT / "src/i2c_accel.c").read_text(encoding="utf-8")
HW_INIT = (ROOT / "src/hw_init.c").read_text(encoding="utf-8")

assert "#define DA218E_I2C_ADDR" in CONFIG and "0x26" in CONFIG
assert "DA218E_I2C_FALLBACK_ADDR" in CONFIG
assert "DA218E_I2C_LEGACY_ADDR" in CONFIG
assert "DA218E_I2C_LEGACY_FALLBACK_ADDR" in CONFIG
assert "DA218E_INIT_MAX_RETRIES" in DRIVER
assert "for (uint8_t attempt = 0; attempt < DA218E_INIT_MAX_RETRIES; attempt++)" in DRIVER
assert "uint8_t addrs[4]" in DRIVER
assert "[ACCEL] probe addr=0x%02x" in DRIVER
assert "[ACCEL] bus pre SCL=%u SDA=%u" in HW_INIT
assert "[ACCEL] bus af SCL=%u SDA=%u" in DRIVER
assert "[ACCEL] bus post SCL=%u SDA=%u" in DRIVER
for stage in ("BUS", "START", "ADDR-W", "REG", "RESTART", "ADDR-R", "DATA"):
    assert f'DA218E_FAIL_{stage.replace("-", "_")}' in DRIVER
assert "[ACCEL] fail addr=0x%02x stage=%s" in DRIVER
assert "I2C_EnableSoftwareReset(BSP_I2C, ENABLE)" in DRIVER
assert "I2C_SendAddr7bit(BSP_I2C, (uint8_t)(addr << 1)" in DRIVER
assert "I2C_SendAddr7bit(BSP_I2C, (uint8_t)(s_addr << 1)" in DRIVER
assert "return;" in DRIVER

print("DA218E I2C contract: PASS")
