#ifndef CONFIG_H
#define CONFIG_H

#include "n32l40x.h"

/* ── Firmware version ─────────────────────────────────────────────────────── */
#define FW_VERSION_STR   "T663B_B409_20251125"
#define FW_MODEL_STR     "T663B"

/* ── System clock ─────────────────────────────────────────────────────────── */
#define SYS_CLOCK_HZ     64000000UL   /* SYSCLK = 64 MHz (HSI PLL x8) */
#define APB1_CLOCK_HZ    16000000UL   /* APB1 = 16 MHz (DIV4) — USART2/3 */
#define APB2_CLOCK_HZ    32000000UL   /* APB2 = 32 MHz (DIV2) — USART1, SPI1 */

/* ── Tick ─────────────────────────────────────────────────────────────────── */
extern volatile uint32_t g_tick_ms;
#define TICK_MS()        (g_tick_ms)

/* ═══════════════════════════════════════════════════════════════════════════
 * GPIO PIN ASSIGNMENTS  (N32L406CDL7, LQFP-48)
 * ═══════════════════════════════════════════════════════════════════════════ */

/* ── 4G modem EC800M (UART5, not USART3!) ────────────────────────────────── */
#define EC800M_UART         UART5             /* 改：实际硬件使用 UART5 */
#define EC800M_UART_CLK     RCC_APB2_PERIPH_UART5  /* ⚠️ UART5 在 APB2 */
#define EC800M_BAUD         115200

#define EC800M_TX_PORT      GPIOB
#define EC800M_TX_PIN       GPIO_PIN_4        /* PB4 UART5_TX → EC800M RXD (AF6) */
#define EC800M_RX_PORT      GPIOB
#define EC800M_RX_PIN       GPIO_PIN_5        /* PB5 UART5_RX ← EC800M TXD (AF7) */
#define EC800M_PWRKEY_PORT  GPIOA
#define EC800M_PWRKEY_PIN   GPIO_PIN_8        /* PA8  → EC800M PWRKEY (改：原PA9) */
#define EC800M_DTR_PORT     GPIOB
#define EC800M_DTR_PIN      GPIO_PIN_7        /* PB7 → EC800M DTR (改：原PB13) */

/* 新增：模组电源使能（PA15=GPRS_POWER_EN，高电平使能） */
#define EC800M_POWER_EN_PORT  GPIOA
#define EC800M_POWER_EN_PIN   GPIO_PIN_15

/* DMA for EC800M RX — UART5_RX → DMA_CH4 (查数据手册确认) */
#define EC800M_DMA           DMA
#define EC800M_DMA_CH_RX     DMA_CH4          /* 改：UART5 对应 CH4 */
#define EC800M_RX_BUF_SIZE   1024

/* ── GPS module TAU804M (USART2) ──────────────────────────────────────────── */
#define GPS_UART             USART2
#define GPS_UART_CLK         RCC_APB1_PERIPH_USART2
#define GPS_BAUD             9600

#define GPS_TX_PORT          GPIOA
#define GPS_TX_PIN           GPIO_PIN_2        /* PA2 USART2_TX → GPS RX */
#define GPS_RX_PORT          GPIOA
#define GPS_RX_PIN           GPIO_PIN_3        /* PA3 USART2_RX ← GPS TX */
#define GPS_EN_PORT          GPIOB
#define GPS_EN_PIN           GPIO_PIN_6        /* PB6 high = GPS LDO enable */

/* ── Debug UART (USART1 on PA9=TX / PA10=RX, AF4) ────────────────────────── */
#define DBG_UART             USART1
#define DBG_UART_CLK         RCC_APB2_PERIPH_USART1
#define DBG_BAUD             115200
#define DBG_TX_PORT          GPIOA
#define DBG_TX_PIN           GPIO_PIN_9        /* PA9  LOG_TX */
#define DBG_RX_PORT          GPIOA
#define DBG_RX_PIN           GPIO_PIN_10       /* PA10 LOG_RX */

/* ── SPI Flash BY25Q16 (SPI1) ─────────────────────────────────────────────── */
#define FLASH_SPI            SPI1
#define FLASH_SPI_CLK        RCC_APB2_PERIPH_SPI1
#define FLASH_SCK_PORT       GPIOA
#define FLASH_SCK_PIN        GPIO_PIN_5        /* PA5 SPI1_SCK  (改：原PB3) */
#define FLASH_MISO_PORT      GPIOA
#define FLASH_MISO_PIN       GPIO_PIN_6        /* PA6 SPI1_MISO (改：原PB4) */
#define FLASH_MOSI_PORT      GPIOA
#define FLASH_MOSI_PIN       GPIO_PIN_7        /* PA7 SPI1_MOSI (改：原PB5) */
#define FLASH_CS_PORT        GPIOA
#define FLASH_CS_PIN         GPIO_PIN_4        /* PA4 SPI1_NSS  (改：原PA15) */

#define FLASH_CS_LOW()   GPIO_ResetBits(FLASH_CS_PORT, FLASH_CS_PIN)
#define FLASH_CS_HIGH()  GPIO_SetBits(FLASH_CS_PORT, FLASH_CS_PIN)

/* ── I2C (I2C1 PB6/PB7) ──────────────────────────────────────────────────── */
#define BSP_I2C              I2C1
#define BSP_I2C_CLK          RCC_APB1_PERIPH_I2C1
#define BSP_I2C_SCL_PORT     GPIOB
#define BSP_I2C_SCL_PIN      GPIO_PIN_6        /* PB6 I2C1_SCL (shared w/ GPS_EN) */
#define BSP_I2C_SDA_PORT     GPIOB
#define BSP_I2C_SDA_PIN      GPIO_PIN_7        /* PB7 I2C1_SDA */

/* DA218E accelerometer I2C address (SDO=GND → 0x26, SDO=VCC → 0x27) */
#define DA218E_I2C_ADDR      0x26

/* ── ADC ──────────────────────────────────────────────────────────────────── */
/* PA0 CAR_ADC: R1(180K)+R2(5.6K) divider → V_car = adc_v * 33.2 */
#define ADC_CAR_PORT         GPIOA
#define ADC_CAR_PIN          GPIO_PIN_0        /* PA0 ADC1_IN1  */
#define ADC_CAR_CH           ADC_CH_1
#define ADC_CAR_RATIO        33.2f

/* PA1 BAT_ADC: R69(910K)+R71(390K) divider → V_bat = adc_v * 3.33 */
#define ADC_BAT_PORT         GPIOA
#define ADC_BAT_PIN          GPIO_PIN_1        /* PA1 ADC1_IN2  */
#define ADC_BAT_CH           ADC_CH_2
#define ADC_BAT_RATIO        3.33f

/* ── Digital IO ───────────────────────────────────────────────────────────── */
#define ACC_DET_PORT         GPIOA
#define ACC_DET_PIN          GPIO_PIN_3        /* PA3  ACC ignition detect */
#define SOS_PORT             GPIOA
#define SOS_PIN              GPIO_PIN_4        /* PA4  SOS button (⚠️ 与 FLASH_CS 冲突，待核实) */
#define DC_UP_PORT           GPIOA
#define DC_UP_PIN            GPIO_PIN_8        /* PA8  external DC detect (⚠️ 与 EC800M_PWRKEY 冲突) */
#define RELAY_PORT           GPIOA
#define RELAY_PIN            GPIO_PIN_10       /* PA10 OIL_CTR relay out   */
#define LIGHT_INT_PORT       GPIOB
#define LIGHT_INT_PIN        GPIO_PIN_0        /* PB0  light sensor IRQ    */
#define GPS_LED_PORT         GPIOD
#define GPS_LED_PIN          GPIO_PIN_0        /* PD0 GPS status LED (blue) (改：原PB14) */

/* RS485 */
#define RS485_TX_PORT        GPIOB
#define RS485_TX_PIN         GPIO_PIN_8
#define RS485_RX_PORT        GPIOB
#define RS485_RX_PIN         GPIO_PIN_9
#define RS485_CE_PORT        GPIOB
#define RS485_CE_PIN         GPIO_PIN_12       /* high=TX, low=RX          */

/* ── Watchdog ─────────────────────────────────────────────────────────────── */
#define IWDG_RELOAD_MS       5000

/* ── JT808 defaults ───────────────────────────────────────────────────────── */
#define JT808_DEFAULT_PORT   8898
#define HEARTBEAT_DEFAULT_S  60

/* ── EC800M TCP channels ──────────────────────────────────────────────────── */
#define TCP_CH_MAIN          0   /* primary JT808 server   */
#define TCP_CH_OTA           1   /* OTA / FOTA server      */
#define TCP_CH_AGPS          2   /* AGPS server            */
#define TCP_CH_BACKUP        3   /* backup JT808 server    */
#define TCP_CH_NTRIP         4   /* NTRIP RTK              */

#endif /* CONFIG_H */
