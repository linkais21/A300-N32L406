from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
CONFIG = (ROOT / "include/config.h").read_text(encoding="utf-8")
HW_INIT = (ROOT / "src/hw_init.c").read_text(encoding="utf-8")
GPS = (ROOT / "src/gps.c").read_text(encoding="utf-8")
POWER = (ROOT / "src/power_mgr.c").read_text(encoding="utf-8")
SLEEP = (ROOT / "src/work_mode_sleep.c").read_text(encoding="utf-8")
MAIN = (ROOT / "src/main.c").read_text(encoding="utf-8")


def define(name: str) -> str:
    match = re.search(rf"^#define\s+{re.escape(name)}\s+([^\s/]+)", CONFIG, re.MULTILINE)
    assert match is not None, f"missing #define {name}"
    return match.group(1)


expected = {
    "ACC_DET_PORT": "GPIOA",
    "ACC_DET_PIN": "GPIO_PIN_12",
    "ADC_CAR_PORT": "GPIOA",
    "ADC_CAR_PIN": "GPIO_PIN_3",
    "ADC_CAR_CH": "ADC_CH_4",
    "BSP_I2C": "I2C2",
    "BSP_I2C_CLK": "RCC_APB1_PERIPH_I2C2",
    "BSP_I2C_SDA_PORT": "GPIOD",
    "BSP_I2C_SDA_PIN": "GPIO_PIN_14",
    "BSP_I2C_SCL_PORT": "GPIOD",
    "BSP_I2C_SCL_PIN": "GPIO_PIN_15",
    "BSP_I2C_GPIO_AF": "GPIO_AF6_I2C2",
    "DA218E_INT1_PORT": "GPIOB",
    "DA218E_INT1_PIN": "GPIO_PIN_3",
    "FLASH_CS_PORT": "GPIOA",
    "FLASH_CS_PIN": "GPIO_PIN_4",
    "SOS_PORT": "GPIOA",
    "SOS_PIN": "GPIO_PIN_2",
    "LIGHT_INT_PORT": "GPIOA",
    "LIGHT_INT_PIN": "GPIO_PIN_0",
    "GPS_UART": "UART4",
    "GPS_TX_PORT": "GPIOB",
    "GPS_TX_PIN": "GPIO_PIN_0",
    "GPS_RX_PORT": "GPIOB",
    "GPS_RX_PIN": "GPIO_PIN_1",
    "GPS_EN_PORT": "GPIOB",
    "GPS_EN_PIN": "GPIO_PIN_6",
    "EC800M_UART": "UART5",
    "EC800M_TX_PORT": "GPIOB",
    "EC800M_TX_PIN": "GPIO_PIN_4",
    "EC800M_RX_PORT": "GPIOB",
    "EC800M_RX_PIN": "GPIO_PIN_5",
    "EC800M_DTR_PORT": "GPIOB",
    "EC800M_DTR_PIN": "GPIO_PIN_7",
    "DBG_UART": "USART1",
    "DBG_TX_PORT": "GPIOA",
    "DBG_TX_PIN": "GPIO_PIN_9",
    "DBG_RX_PORT": "GPIOA",
    "DBG_RX_PIN": "GPIO_PIN_10",
}

for name, value in expected.items():
    actual = define(name)
    assert actual == value, f"{name}: expected {value}, got {actual}"

assert define("BSP_I2C_SCL_PIN") != define("GPS_EN_PIN")
assert define("BSP_I2C_SDA_PIN") != define("EC800M_DTR_PIN")
assert (define("FLASH_CS_PORT"), define("FLASH_CS_PIN")) != (
    define("SOS_PORT"), define("SOS_PIN")
)

assert "g.GPIO_Alternate = BSP_I2C_GPIO_AF;" in HW_INIT
assert "GPIO_AF0_SPI1" in HW_INIT
assert "GPIO_AF5_SPI1" not in HW_INIT
assert "gpio_input(DA218E_INT1_PORT, DA218E_INT1_PIN, GPIO_No_Pull);" in HW_INIT
assert "gpio_input(SOS_PORT, SOS_PIN, GPIO_Pull_Up);" in HW_INIT
assert "g.Pin = ADC_CAR_PIN | ADC_BAT_PIN;" in HW_INIT
miso_pin = HW_INIT.index("g.Pin            = FLASH_MISO_PIN;")
miso_start = HW_INIT.rfind("g.GPIO_Mode", 0, miso_pin)
miso_end = HW_INIT.index("GPIO_InitPeripheral(FLASH_MISO_PORT, &g);", miso_pin)
miso_block = HW_INIT[miso_start:miso_end]
assert "g.GPIO_Mode      = GPIO_Mode_Input;" in miso_block
assert "GPIO_Mode_AF_PP" not in miso_block
assert "GPIO_AF4_I2C1" not in GPS
assert "GPIO_Mode_AF_OD" not in GPS

assert re.search(r"gpio_input\(ACC_DET_PORT,\s*ACC_DET_PIN,\s*GPIO_Pull_Up\);", HW_INIT)
assert "bool hw_acc_is_on(void)" in (ROOT / "src/hw_init.c").read_text(encoding="utf-8")
assert "GPIO_PIN_SOURCE12" in SLEEP
assert "EXTI_Trigger_Rising_Falling, EXTI15_10_IRQn" in SLEEP
assert "void EXTI15_10_IRQHandler(void)" in POWER
for line in ("EXTI_LINE12", "EXTI_LINE15"):
    assert f"EXTI_GetITStatus({line})" in POWER
    assert f"EXTI_ClrITPendBit({line})" in POWER
assert "void EXTI3_IRQHandler(void)" not in POWER
assert "EXTI_LINE3" not in POWER
assert "GPIOA_PORT_SOURCE, GPIO_PIN_SOURCE2" in SLEEP
assert "EXTI_Trigger_Falling, EXTI2_IRQn" in SLEEP
assert "void EXTI2_IRQHandler(void)" in POWER
assert "EXTI_GetITStatus(EXTI_LINE2)" in POWER
assert "EXTI_ClrITPendBit(EXTI_LINE2)" in POWER
assert "void EXTI4_IRQHandler(void)" not in POWER
assert "EXTI_LINE4" not in POWER
exti2 = POWER[POWER.index("void EXTI2_IRQHandler(void)"):]
exti2 = exti2[:exti2.index("void EXTI15_10_IRQHandler(void)")]
assert "jt808_trigger_alarm" not in exti2

banner = "[HW] ACC=PA12 pin_high=%u acc_on=%u logical_acc=%u CAR_ADC=PA3/CH4 I2C=I2C2/PD14/PD15 DA218E_INT1=%u"
assert banner in MAIN
assert "hw_acc_pin_high()" in MAIN
assert "hw_acc_is_on()" in MAIN
assert "work_mode_logical_acc()" in MAIN
assert "GPIO_ReadInputDataBit(DA218E_INT1_PORT, DA218E_INT1_PIN)" in MAIN
assert MAIN.count("[HW] ACC=PA12") == 1

print("Hardware pin contract: PASS")
