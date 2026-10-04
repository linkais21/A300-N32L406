from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DRIVER = (ROOT / "src/i2c_accel.c").read_text(encoding="utf-8")
HEADER = (ROOT / "include/i2c_accel.h").read_text(encoding="utf-8")
MAIN = (ROOT / "src/main.c").read_text(encoding="utf-8")
HW_INIT = (ROOT / "src/hw_init.c").read_text(encoding="utf-8")

assert "i2c_accel_bus_preinit_probe" not in HEADER
assert "[ACCEL] bus pre SCL=%u SDA=%u" in HW_INIT
assert HW_INIT.index("[ACCEL] bus pre SCL=%u SDA=%u") < HW_INIT.index("g.GPIO_Mode      = GPIO_Mode_AF_OD")
assert "DA218E_BUS_RECOVERY_CLOCKS 9U" in DRIVER
assert "for (pulses = 0U; pulses < DA218E_BUS_RECOVERY_CLOCKS; ++pulses)" in DRIVER
assert "GPIO_Mode_Out_OD" in DRIVER
assert "GPIO_SetBits(BSP_I2C_SCL_PORT, BSP_I2C_SCL_PIN)" in DRIVER
assert "GPIO_ResetBits(BSP_I2C_SCL_PORT, BSP_I2C_SCL_PIN)" in DRIVER
assert "GPIO_ResetBits(BSP_I2C_SDA_PORT, BSP_I2C_SDA_PIN)" in DRIVER
assert "GPIO_SetBits(BSP_I2C_SDA_PORT, BSP_I2C_SDA_PIN)" in DRIVER
assert "hw_i2c_init();" in DRIVER
assert "[ACCEL] bus af SCL=%u SDA=%u STS1=%04x STS2=%04x" in DRIVER
assert "[ACCEL] recovery released SCL=%u SDA=%u" in DRIVER
assert "[ACCEL] recovery pulses=%u SCL=%u SDA=%u" in DRIVER
assert "[ACCEL] bus post SCL=%u SDA=%u STS1=%04x STS2=%04x" in DRIVER

print("I2C bus recovery contract: PASS")
