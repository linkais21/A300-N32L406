# A300-T9 固件修改记录 (2026-06-05)

## 修改目的
修正硬件引脚定义错误，解决 4G 模组通信失败问题。

## 问题描述
原固件使用错误的引脚配置：
- 4G 模组使用 USART3 (PB14/PB15) — **错误**，实际硬件使用 UART5 (PB4/PB5)
- SPI Flash 使用 PB3/PB4/PB5 — **错误**，实际硬件使用 PA5/PA6/PA7
- GPS LED 使用 PB14 — **错误**，实际硬件使用 PD0
- 缺少 4G 模组电源使能控制 (PA15)

导致现象：
```
>> AT
>> AT
>> AT
[4G] no AT response, reset
```

---

## 修改内容

### 1. `include/config.h` — 引脚重定义

#### 1.1 EC800M 4G 模组（UART5）
```c
// 旧配置（错误）
#define EC800M_UART         USART3
#define EC800M_UART_CLK     RCC_APB1_PERIPH_USART3
#define EC800M_TX_PORT      GPIOB
#define EC800M_TX_PIN       GPIO_PIN_14       /* PB14 USART3_TX */
#define EC800M_RX_PORT      GPIOB
#define EC800M_RX_PIN       GPIO_PIN_15       /* PB15 USART3_RX */
#define EC800M_PWRKEY_PORT  GPIOA
#define EC800M_PWRKEY_PIN   GPIO_PIN_9        /* PA9 PWRKEY */
#define EC800M_DTR_PORT     GPIOB
#define EC800M_DTR_PIN      GPIO_PIN_13       /* PB13 DTR */

// 新配置（正确）
#define EC800M_UART         UART5             /* 改：实际硬件使用 UART5 */
#define EC800M_UART_CLK     RCC_APB2_PERIPH_UART5  /* ⚠️ UART5 在 APB2 */
#define EC800M_TX_PORT      GPIOB
#define EC800M_TX_PIN       GPIO_PIN_4        /* PB4 UART5_TX (AF6) */
#define EC800M_RX_PORT      GPIOB
#define EC800M_RX_PIN       GPIO_PIN_5        /* PB5 UART5_RX (AF7) */
#define EC800M_PWRKEY_PORT  GPIOA
#define EC800M_PWRKEY_PIN   GPIO_PIN_8        /* PA8 PWRKEY */
#define EC800M_DTR_PORT     GPIOB
#define EC800M_DTR_PIN      GPIO_PIN_7        /* PB7 DTR */

/* 新增：模组电源使能（PA15，高电平使能） */
#define EC800M_POWER_EN_PORT  GPIOA
#define EC800M_POWER_EN_PIN   GPIO_PIN_15
```

**关键注意事项**：
- UART5 的 TX/RX 使用**不对称 AF**：PB4=AF6 (TX)，PB5=AF7 (RX)
- UART5 时钟在 **APB2**，不是 APB1
- DMA 通道改为 DMA_CH4（UART5 对应）

#### 1.2 SPI Flash (SPI1)
```c
// 旧配置（错误）
#define FLASH_SCK_PORT       GPIOB
#define FLASH_SCK_PIN        GPIO_PIN_3        /* PB3 SPI1_SCK */
#define FLASH_MISO_PORT      GPIOB
#define FLASH_MISO_PIN       GPIO_PIN_4        /* PB4 SPI1_MISO */
#define FLASH_MOSI_PORT      GPIOB
#define FLASH_MOSI_PIN       GPIO_PIN_5        /* PB5 SPI1_MOSI */
#define FLASH_CS_PORT        GPIOA
#define FLASH_CS_PIN         GPIO_PIN_15       /* PA15 CS */

// 新配置（正确）
#define FLASH_SCK_PORT       GPIOA
#define FLASH_SCK_PIN        GPIO_PIN_5        /* PA5 SPI1_SCK */
#define FLASH_MISO_PORT      GPIOA
#define FLASH_MISO_PIN       GPIO_PIN_6        /* PA6 SPI1_MISO */
#define FLASH_MOSI_PORT      GPIOA
#define FLASH_MOSI_PIN       GPIO_PIN_7        /* PA7 SPI1_MOSI */
#define FLASH_CS_PORT        GPIOA
#define FLASH_CS_PIN         GPIO_PIN_4        /* PA4 CS */
```

#### 1.3 GPS LED
```c
// 旧配置（错误）
#define GPS_LED_PORT         GPIOB
#define GPS_LED_PIN          GPIO_PIN_14       /* PB14 */

// 新配置（正确）
#define GPS_LED_PORT         GPIOD
#define GPS_LED_PIN          GPIO_PIN_0        /* PD0 (BOOT0) */
```

---

### 2. `src/hw_init.c` — 硬件初始化

#### 2.1 GPIO 时钟使能（增加 GPIOD）
```c
// 旧代码
RCC_EnableAPB2PeriphClk(RCC_APB2_PERIPH_GPIOA | RCC_APB2_PERIPH_GPIOB |
                         RCC_APB2_PERIPH_GPIOC | RCC_APB2_PERIPH_AFIO,
                         ENABLE);

// 新代码
RCC_EnableAPB2PeriphClk(RCC_APB2_PERIPH_GPIOA | RCC_APB2_PERIPH_GPIOB |
                         RCC_APB2_PERIPH_GPIOC | RCC_APB2_PERIPH_GPIOD |  // ← 新增
                         RCC_APB2_PERIPH_AFIO,
                         ENABLE);
```

#### 2.2 GPIO 初始化（新增 4G 电源使能）
```c
/* 新增：EC800M 模组电源使能 (PA15, 高电平使能) */
gpio_out_pp(EC800M_POWER_EN_PORT, EC800M_POWER_EN_PIN);
GPIO_SetBits(EC800M_POWER_EN_PORT, EC800M_POWER_EN_PIN);
```

#### 2.3 UART5 初始化
```c
// 旧代码
/* ── USART3 EC800M (PB14=TX AF7, PB15=RX AF7) ────────────────────────── */
RCC_EnableAPB1PeriphClk(EC800M_UART_CLK, ENABLE);
gpio_af_tx(EC800M_TX_PORT, EC800M_TX_PIN, GPIO_AF7_USART3);
gpio_af_rx(EC800M_RX_PORT, EC800M_RX_PIN, GPIO_AF7_USART3);

// 新代码
/* ── UART5 EC800M (PB4=TX AF6, PB5=RX AF7 ⚠️不对称AF) ─────────────────── */
RCC_EnableAPB2PeriphClk(EC800M_UART_CLK, ENABLE);  // ← APB2！
gpio_af_tx(EC800M_TX_PORT, EC800M_TX_PIN, GPIO_AF6_UART5);  // ← AF6
gpio_af_rx(EC800M_RX_PORT, EC800M_RX_PIN, GPIO_AF7_UART5);  // ← AF7
```

#### 2.4 NVIC 中断配置
```c
// 旧代码
/* USART3 EC800M RX (priority 1) */
n.NVIC_IRQChannel = USART3_IRQn;

// 新代码
/* UART5 EC800M RX (priority 1) */
n.NVIC_IRQChannel = UART5_IRQn;
```

---

### 3. `src/ec800m.c` — 中断处理函数

```c
// 旧代码
void USART3_IRQHandler(void)
{
    if (USART_GetIntStatus(EC800M_UART, USART_INT_RXDNE)) {

// 新代码
void UART5_IRQHandler(void)  // ← 函数名改！
{
    if (USART_GetIntStatus(EC800M_UART, USART_INT_RXDNE)) {
```

---

### 4. `src/main.c` — 注释更新

```c
// 旧注释
/* EC800M RX is now handled by USART3_IRQHandler() inside ec800m.c. */
hw_usart_init();   /* USART1=debug(PA9/PA10), USART2=GPS, USART3=EC800M */

// 新注释
/* EC800M RX is now handled by UART5_IRQHandler() inside ec800m.c. */
hw_usart_init();   /* USART1=debug(PA9/PA10), USART2=GPS, UART5=EC800M */
```

---

## 编译结果

```
Memory region         Used Size  Region Size  %age Used
           FLASH:       86028 B       384 KB     21.88%
             RAM:       12588 B        32 KB     38.42%
```

**生成文件**：
- `build/a300_firmware.elf` — ELF 可执行文件
- `build/a300_firmware.hex` — Intel HEX 格式固件（241900 字节）
- `build/a300_firmware.bin` — 二进制固件（86028 字节）

---

## 引脚对照表（修正后）

| 功能 | 旧定义（错） | 新定义（对） | 复用功能 |
|------|------------|------------|---------|
| **4G TX** | PB14 (USART3) | PB4 (UART5) | GPIO_AF6_UART5 |
| **4G RX** | PB15 (USART3) | PB5 (UART5) | GPIO_AF7_UART5 |
| **4G PWRKEY** | PA9 | PA8 | GPIO_OUT |
| **4G DTR** | PB13 | PB7 | GPIO_OUT |
| **4G 电源使能** | （缺失） | PA15 | GPIO_OUT（高有效） |
| **Flash CS** | PA15 | PA4 | GPIO_OUT |
| **Flash SCK** | PB3 | PA5 | GPIO_AF0_SPI1 |
| **Flash MISO** | PB4 | PA6 | GPIO_AF0_SPI1 |
| **Flash MOSI** | PB5 | PA7 | GPIO_AF0_SPI1 |
| **GPS LED** | PB14 | PD0 | GPIO_OUT |

---

## 预期效果

烧录修正后的固件，应该看到：

```
[4G] power on
>> AT
<< OK
>> AT+CGSN
<< 86XXXXXXXXXXXX
>> AT+CSQ
<< +CSQ: 18,99
>> AT+CGREG?
<< +CGREG: 0,1
[4G] registered to network
[STATUS] t=10s 4G=REG GPS=SRH lat=0.000000 lon=0.000000 spd=0.0 vcar=12.5V vbat=4.11V csq=18
```

**不再出现**：
- `[4G] no AT response, reset` 循环死机
- 4G 模组无响应

---

## 验证步骤

1. 烧录固件：`build/a300_firmware.hex`
2. 串口监视器连接调试口 (PA9=TX, PA10=RX, 115200 baud)
3. 上电，观察启动日志
4. 确认 4G 模组初始化成功（有 `OK` 响应）
5. 确认 SPI Flash 读取成功（`[FLASH] ID=0x...`）
6. 确认 GPS LED 控制正常（定位后蓝灯常亮）

---

## 修改者
- 日期: 2026-06-05
- 编译器: arm-none-eabi-gcc 14.3.1
- MCU: N32L406CDL7 (384K Flash, 32K RAM)
