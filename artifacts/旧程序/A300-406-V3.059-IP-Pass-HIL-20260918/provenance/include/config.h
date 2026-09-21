#ifndef CONFIG_H
#define CONFIG_H

#include "n32l40x.h"

/* ── Firmware version ─────────────────────────────────────────────────────── */
#define FW_VERSION_STR          "T360-A300_406_20260918144414,V3.059"
#define FW_OTA_MODEL_STR        "A300-406"
#define FW_JT808_MODEL_STR      "T360-A300"
#define FW_MANUFACTURER_ID_STR  "70110"

/* ── System clock ─────────────────────────────────────────────────────────── */
#define SYS_CLOCK_HZ     64000000UL   /* SYSCLK = 64 MHz (HSI PLL, SDK-supported) */
#define APB1_CLOCK_HZ    16000000UL   /* APB1 = 16 MHz (DIV4) — USART2/3 */
#define APB2_CLOCK_HZ    32000000UL   /* APB2 = 32 MHz (DIV2) — USART1, SPI1 */

/* ── Tick ─────────────────────────────────────────────────────────────────── */
extern volatile uint32_t g_tick_ms;
#define TICK_MS()        (g_tick_ms)

/* ═══════════════════════════════════════════════════════════════════════════
 * GPIO PIN ASSIGNMENTS  (N32L406CBL7, LQFP-48)
 * ═══════════════════════════════════════════════════════════════════════════ */

/* ── 4G modem EC800M (UART5 on PB4/PB5) ───────────────────────────────────── */
#define EC800M_UART         UART5             /* 原理图确认：UART5 (PB4/PB5) ⚠️ */
#define EC800M_UART_CLK     RCC_APB2_PERIPH_UART5  /* UART5 在 APB2 */
#define EC800M_BAUD         115200

#define EC800M_TX_PORT      GPIOB
#define EC800M_TX_PIN       GPIO_PIN_4        /* PB4 UART5_TX → EC800M MAIN_RXD */
#define EC800M_RX_PORT      GPIOB
#define EC800M_RX_PIN       GPIO_PIN_5        /* PB5 UART5_RX ← EC800M MAIN_TXD */

#define EC800M_PWRKEY_PORT  GPIOA
#define EC800M_PWRKEY_PIN   GPIO_PIN_8        /* PA8  4G_POWER_KEY (原理图确认) */
#define EC800M_DTR_PORT     GPIOB
#define EC800M_DTR_PIN      GPIO_PIN_7        /* PB7 → EC800M DTR (引脚43) */

/* 新增：模组电源使能 (PA15，高电平使能) */
#define EC800M_POWER_EN_PORT  GPIOA
#define EC800M_POWER_EN_PIN   GPIO_PIN_15     /* PA15 GPRS_POWER_EN (引脚38) */

/* DMA for EC800M RX — UART5_RX → DMA2_CH5 */
#define EC800M_DMA           DMA
#define EC800M_DMA_CH_RX     DMA_CH5           /* UART5 RX remapped to DMA channel 5 */
#define EC800M_RX_BUF_SIZE   1024

/* 全局DMA接收缓冲区（定义在ec800m.c） */
extern uint8_t EC800M_RX_BUF[EC800M_RX_BUF_SIZE];

/* ── GPS module TAU804M (UART4 on PB0/PB1) ───────────────────────────────── */
#define GPS_UART             UART4
#define GPS_UART_CLK         RCC_APB2_PERIPH_UART4   /* UART4 on APB2 */
#define GPS_UART_IRQn        UART4_IRQn
#define GPS_BAUD             115200

#define GPS_TX_PORT          GPIOB
#define GPS_TX_PIN           GPIO_PIN_0        /* PB0 UART4_TX → GPS RX */
#define GPS_RX_PORT          GPIOB
#define GPS_RX_PIN           GPIO_PIN_1        /* PB1 UART4_RX ← GPS TX (MCU pin 19) */
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
#define FLASH_SCK_PIN        GPIO_PIN_5        /* PA5 SPI1_SCK */
#define FLASH_MISO_PORT      GPIOA
#define FLASH_MISO_PIN       GPIO_PIN_6        /* PA6 SPI1_MISO */
#define FLASH_MOSI_PORT      GPIOA
#define FLASH_MOSI_PIN       GPIO_PIN_7        /* PA7 SPI1_MOSI */
#define FLASH_CS_PORT        GPIOA
#define FLASH_CS_PIN         GPIO_PIN_4        /* PA4 SPI1_CS */

#define FLASH_CS_LOW()   GPIO_ResetBits(FLASH_CS_PORT, FLASH_CS_PIN)
#define FLASH_CS_HIGH()  GPIO_SetBits(FLASH_CS_PORT, FLASH_CS_PIN)

/* ── DA218E I2C (I2C2 on PD14/PD15; HSI clock required) ─────────────────── */
#define BSP_I2C              I2C2
#define BSP_I2C_CLK          RCC_APB1_PERIPH_I2C2
#define BSP_I2C_SDA_PORT     GPIOD
#define BSP_I2C_SDA_PIN      GPIO_PIN_14       /* PD14 I2C2_SDA / OSC_IN */
#define BSP_I2C_SCL_PORT     GPIOD
#define BSP_I2C_SCL_PIN      GPIO_PIN_15       /* PD15 I2C2_SCL / OSC_OUT */
#define BSP_I2C_GPIO_AF      GPIO_AF6_I2C2

#define DA218E_INT1_PORT     GPIOB
#define DA218E_INT1_PIN      GPIO_PIN_3        /* PB3 SOR_INT1 */

/* DA218E address: board SDO=GND -> 0x26; retain 0x27 for compatible batches. */
#define DA218E_I2C_ADDR           0x26
#define DA218E_I2C_FALLBACK_ADDR  0x27
/* Some DA218E batches document 0x26/0x27 as 8-bit address bytes; support
 * their equivalent 7-bit forms 0x13/0x14 as a compatibility probe. */
#define DA218E_I2C_LEGACY_ADDR           0x13
#define DA218E_I2C_LEGACY_FALLBACK_ADDR  0x14

/* ── ADC ──────────────────────────────────────────────────────────────────── */
/* PA3 CAR_ADC: R1(180K)+R2(5.6K) divider → V_car = adc_v * 33.2 */
#define ADC_CAR_PORT         GPIOA
#define ADC_CAR_PIN          GPIO_PIN_3        /* PA3 ADC_IN4 */
#define ADC_CAR_CH           ADC_CH_4
#define ADC_CAR_RATIO        33.2f

/* PA1 BAT_ADC: R69(910K)+R71(390K) divider → V_bat = adc_v * 3.33 */
#define ADC_BAT_PORT         GPIOA
#define ADC_BAT_PIN          GPIO_PIN_1        /* PA1 ADC1_IN2  */
#define ADC_BAT_CH           ADC_CH_2
#define ADC_BAT_RATIO        3.33f

/* ── Digital IO ───────────────────────────────────────────────────────────── */
#define ACC_DET_PORT         GPIOA
#define ACC_DET_PIN          GPIO_PIN_12       /* PA12 M_ACC_IN via Q9, low = ACC ON */
#define SOS_PORT             GPIOA
#define SOS_PIN              GPIO_PIN_2        /* PA2 M_SOS button */
#define DC_UP_PORT           GPIOB
#define DC_UP_PIN            GPIO_PIN_15       /* PB15 DC_UP_EN (引脚28) 充电使能检测 */
#define RELAY_PORT           GPIOA
#define RELAY_PIN            GPIO_PIN_11       /* PA11 OIL_CTR relay out (原理图确认) */
#define LIGHT_INT_PORT       GPIOA
#define LIGHT_INT_PIN        GPIO_PIN_0        /* PA0 GUANG_INT light sensor IRQ */
#define GPS_LED_PORT         GPIOD
#define GPS_LED_PIN          GPIO_PIN_0        /* PD0 GPS status LED (blue) — 原理图确认 2026-06-05 */

/* RS485 */
#define RS485_TX_PORT        GPIOB
#define RS485_TX_PIN         GPIO_PIN_10       /* PB10 RS485_TX (原理图确认) */
#define RS485_RX_PORT        GPIOB
#define RS485_RX_PIN         GPIO_PIN_11       /* PB11 RS485_RX (原理图确认) */
#define RS485_CE_PORT        GPIOB
#define RS485_CE_PIN         GPIO_PIN_12       /* PB12 high=TX, low=RX */

/* ── Watchdog ─────────────────────────────────────────────────────────────── */
#define IWDG_RELOAD_MS       5000

/* ── JT808 defaults ───────────────────────────────────────────────────────── */
#define JT808_DEFAULT_PORT   8898
#define HEARTBEAT_DEFAULT_S  180

/* ── EC800M TCP channels ──────────────────────────────────────────────────── */
#define TCP_CH_MAIN          0   /* primary JT808 server   */
#define TCP_CH_OTA           1   /* OTA / FOTA server      */
#define TCP_CH_AGPS          2   /* AGPS server            */
#define TCP_CH_BACKUP        3   /* backup JT808 server    */

#endif /* CONFIG_H */
