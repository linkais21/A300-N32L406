#include "hw_init.h"
#include "config.h"
#include "firmware_layout.h"
#include "n32l40x.h"
#include "debug_uart.h"  /* include debug UART header */

volatile uint32_t g_tick_ms = 0;

void SysTick_Handler(void)
{
    g_tick_ms++;
}

/* ── Clock: configured by system_n32l40x.c SetSysClock() at startup ──────── */
void hw_clock_init(void)
{
    /*
     * SystemInit() (called from startup.s before main) already configured:
     *   SYSCLK = 64 MHz (HSI × 8 via PLL, -DSYSCLK_SRC=3 -DSYSCLK_FREQ=64000000)
     *   AHB    = 64 MHz (DIV1)
     *   APB2   = 32 MHz (DIV2)  — USART1 clock source
     *   APB1   = 16 MHz (DIV4)  — USART2/3 clock source
     *
     * We only start SysTick here.
     */
    NVIC_SetVectorTable(NVIC_VectTab_FLASH,
                        APP_FLASH_BASE - FW_FLASH_BASE);
    SysTick_Config(SYS_CLOCK_HZ / 1000);   /* 1 ms tick at 64 MHz */
}

bool hw_restore_after_stop2(void)
{
    SystemInit();
    hw_clock_init();
    hw_nvic_init();
    hw_gpio_init();
    hw_usart_init();
    hw_spi_init();
    hw_i2c_init();
    hw_adc_init();
    hw_tim_init();
    return SystemCoreClock == SYS_CLOCK_HZ;
}

/* ── GPIO helper: init struct defaults ───────────────────────────────────── */
static void gpio_out_pp(GPIO_Module *port, uint16_t pin)
{
    GPIO_InitType g;
    GPIO_InitStruct(&g);
    g.Pin            = pin;
    g.GPIO_Mode      = GPIO_Mode_Out_PP;
    g.GPIO_Slew_Rate = GPIO_Slew_Rate_High;  /* set to high speed */
    g.GPIO_Current   = GPIO_DC_12mA;         /* set to max 12mA drive */
    g.GPIO_Pull      = GPIO_No_Pull;
    GPIO_InitPeripheral(port, &g);
}

static void gpio_input(GPIO_Module *port, uint16_t pin, GPIO_PuPdType pull)
{
    GPIO_InitType g;
    GPIO_InitStruct(&g);
    g.Pin            = pin;
    g.GPIO_Mode      = GPIO_Mode_Input;
    g.GPIO_Slew_Rate = GPIO_Slew_Rate_Low;
    g.GPIO_Current   = GPIO_DC_4mA;
    g.GPIO_Pull      = pull;
    GPIO_InitPeripheral(port, &g);
}

/* ── GPIO ─────────────────────────────────────────────────────────────────── */
void hw_gpio_init(void)
{
    RCC_EnableAPB2PeriphClk(RCC_APB2_PERIPH_GPIOA | RCC_APB2_PERIPH_GPIOB |
                             RCC_APB2_PERIPH_GPIOC | RCC_APB2_PERIPH_GPIOD |
                             RCC_APB2_PERIPH_AFIO,
                             ENABLE);

    /* ⚠️ Read PA15 initial state (after reset) */
    uint32_t pmode_before = GPIOA->PMODE;
    uint32_t pod_before = GPIOA->POD;
    uint32_t pid_before = GPIOA->PID;

    /* Outputs */
    /* EC800M module power enable (PA15, active high) */
    /* N32L40x PA15 defaults to GPIO after reset, configure directly */
    gpio_out_pp(EC800M_POWER_EN_PORT, EC800M_POWER_EN_PIN);

    /* Read state after config */
    uint32_t pmode_after = GPIOA->PMODE;
    uint32_t pod_after_cfg = GPIOA->POD;
    uint32_t pid_after_cfg = GPIOA->PID;

    GPIO_SetBits(EC800M_POWER_EN_PORT, EC800M_POWER_EN_PIN);

    /* Read state after SetBits */
    uint32_t pod_after_set = GPIOA->POD;
    uint32_t pid_after_set = GPIOA->PID;

    /* Force delay and re-assert PA15 to ensure it takes effect */
    for (int i = 0; i < 10; i++) {
        GPIO_SetBits(EC800M_POWER_EN_PORT, EC800M_POWER_EN_PIN);
        for (volatile int j = 0; j < 10000; j++);
    }

    uint32_t pod_final = GPIOA->POD;
    uint32_t pid_final = GPIOA->PID;

    /* These values are printed in main.c */
    (void)pmode_before; (void)pod_before; (void)pid_before;
    (void)pmode_after; (void)pod_after_cfg; (void)pid_after_cfg;
    (void)pod_after_set; (void)pid_after_set;
    (void)pod_final; (void)pid_final;

    /* Verify PA15 is actually high (for debugging) */
    for (volatile int i = 0; i < 100000; i++);  /* Small delay */
    uint8_t pa15_state = GPIO_ReadOutputDataBit(EC800M_POWER_EN_PORT, EC800M_POWER_EN_PIN);
    (void)pa15_state;  /* Will check this in debugger or set breakpoint */

    gpio_out_pp(EC800M_PWRKEY_PORT, EC800M_PWRKEY_PIN);
    GPIO_SetBits(EC800M_PWRKEY_PORT, EC800M_PWRKEY_PIN);  /* PA8=HIGH = PWRKEY idle (direct connection, no inversion) */

    gpio_out_pp(EC800M_DTR_PORT, EC800M_DTR_PIN);
    GPIO_ResetBits(EC800M_DTR_PORT, EC800M_DTR_PIN);

    gpio_out_pp(GPS_EN_PORT, GPS_EN_PIN);
    GPIO_ResetBits(GPS_EN_PORT, GPS_EN_PIN);

    gpio_out_pp(RELAY_PORT, RELAY_PIN);
    GPIO_ResetBits(RELAY_PORT, RELAY_PIN);

    /* GPS LED — PD0 (BOOT0) */
    gpio_out_pp(GPS_LED_PORT, GPS_LED_PIN);
    GPIO_ResetBits(GPS_LED_PORT, GPS_LED_PIN);

    gpio_out_pp(RS485_CE_PORT, RS485_CE_PIN);
    GPIO_ResetBits(RS485_CE_PORT, RS485_CE_PIN);

    /* Flash CS idle high */
    gpio_out_pp(FLASH_CS_PORT, FLASH_CS_PIN);
    GPIO_SetBits(FLASH_CS_PORT, FLASH_CS_PIN);

    /* Inputs */
    /* M_ACC_IN is the Q9 collector.  Q9 is an inverting NPN level shifter:
     * external ACC ON drives the collector low; the pull-up restores PA12
     * high when the vehicle is off. */
    gpio_input(ACC_DET_PORT,   ACC_DET_PIN,   GPIO_Pull_Up);
    gpio_input(SOS_PORT, SOS_PIN, GPIO_Pull_Up);
    gpio_input(DC_UP_PORT,     DC_UP_PIN,     GPIO_No_Pull);
    gpio_input(LIGHT_INT_PORT, LIGHT_INT_PIN, GPIO_No_Pull);
    gpio_input(DA218E_INT1_PORT, DA218E_INT1_PIN, GPIO_No_Pull);
}

bool hw_acc_is_on(void)
{
    return !hw_acc_pin_high();
}

bool hw_acc_pin_high(void)
{
    return GPIO_ReadInputDataBit(ACC_DET_PORT, ACC_DET_PIN) != Bit_RESET;
}

/* ── USART AF helper ──────────────────────────────────────────────────────── */
static void gpio_af_tx(GPIO_Module *port, uint16_t pin, uint8_t af)
{
    GPIO_InitType g;
    GPIO_InitStruct(&g);
    g.Pin               = pin;
    g.GPIO_Mode         = GPIO_Mode_AF_PP;
    g.GPIO_Slew_Rate    = GPIO_Slew_Rate_High;
    g.GPIO_Current      = GPIO_DC_4mA;
    g.GPIO_Pull         = GPIO_Pull_Up;
    g.GPIO_Alternate    = af;
    GPIO_InitPeripheral(port, &g);
}

static void gpio_af_rx(GPIO_Module *port, uint16_t pin, uint8_t af)
{
    GPIO_InitType g;
    GPIO_InitStruct(&g);
    g.Pin               = pin;
    g.GPIO_Mode         = GPIO_Mode_AF_PP;  /* must be AF mode, not plain Input */
    g.GPIO_Slew_Rate    = GPIO_Slew_Rate_High;
    g.GPIO_Current      = GPIO_DC_4mA;
    g.GPIO_Pull         = GPIO_Pull_Up;
    g.GPIO_Alternate    = af;
    GPIO_InitPeripheral(port, &g);
}

/* ── USART ────────────────────────────────────────────────────────────────── */
void hw_usart_init(void)
{
    USART_InitType u;
    USART_StructInit(&u);
    u.WordLength          = USART_WL_8B;
    u.StopBits            = USART_STPB_1;
    u.Parity              = USART_PE_NO;
    u.HardwareFlowControl = USART_HFCTRL_NONE;
    u.Mode                = USART_MODE_RX | USART_MODE_TX;

    /* ── USART1 debug (PA9=TX AF4, PA10=RX AF4) ──────────────────────────── */
    RCC_EnableAPB2PeriphClk(DBG_UART_CLK, ENABLE);
    gpio_af_tx(DBG_TX_PORT, DBG_TX_PIN, GPIO_AF4_USART1);
    gpio_af_rx(DBG_RX_PORT, DBG_RX_PIN, GPIO_AF4_USART1);
    u.BaudRate = DBG_BAUD;
    USART_Init(DBG_UART, &u);
    USART_Enable(DBG_UART, ENABLE);

    /* ── UART4 GPS (PB0=TX AF6, PB1=RX AF6) ────────────────────────────────── */
    RCC_EnableAPB2PeriphClk(GPS_UART_CLK, ENABLE);   /* UART4 on APB2 */
    gpio_af_tx(GPS_TX_PORT, GPS_TX_PIN, GPIO_AF6_UART4);
    gpio_af_rx(GPS_RX_PORT, GPS_RX_PIN, GPIO_AF6_UART4);
    u.BaudRate = GPS_BAUD;
    USART_Init(GPS_UART, &u);
    USART_ConfigInt(GPS_UART, USART_INT_RXDNE, ENABLE);
    USART_Enable(GPS_UART, ENABLE);

    /* ── UART5 EC800M (PB4=TX AF6, PB5=RX AF7) ⚠️ asymmetric AF ──────────────────── */
    RCC_EnableAPB2PeriphClk(EC800M_UART_CLK, ENABLE);  /* UART5 is on APB2 */
    gpio_af_tx(EC800M_TX_PORT, EC800M_TX_PIN, GPIO_AF6_UART5);  /* PB4 TX=AF6 */
    gpio_af_rx(EC800M_RX_PORT, EC800M_RX_PIN, GPIO_AF7_UART5);  /* PB5 RX=AF7 */
    u.BaudRate = EC800M_BAUD;
    USART_Init(EC800M_UART, &u);

    /* Configure DMA_Channel5 for UART5 RX (based on vendor firmware) */
    RCC_EnableAHBPeriphClk(RCC_AHB_PERIPH_DMA, ENABLE);

    /* ⚠️ Critical: configure DMA Remap to map UART5_RX to DMA_CH5 */
    DMA_RequestRemap(DMA_REMAP_UART5_RX, DMA, DMA_CH5, ENABLE);

    DMA_InitType dma;
    DMA_DeInit(DMA_CH5);
    dma.PeriphAddr     = (uint32_t)&(EC800M_UART->DAT);
    dma.MemAddr        = (uint32_t)EC800M_RX_BUF;
    dma.Direction      = DMA_DIR_PERIPH_SRC;
    dma.BufSize        = EC800M_RX_BUF_SIZE;
    dma.PeriphInc      = DMA_PERIPH_INC_DISABLE;
    dma.DMA_MemoryInc  = DMA_MEM_INC_ENABLE;
    dma.PeriphDataSize = DMA_PERIPH_DATA_SIZE_BYTE;
    dma.MemDataSize    = DMA_MemoryDataSize_Byte;
    dma.CircularMode   = DMA_MODE_CIRCULAR;
    dma.Priority       = DMA_PRIORITY_HIGH;
    dma.Mem2Mem        = DMA_M2M_DISABLE;
    DMA_Init(DMA_CH5, &dma);

    DMA_ConfigInt(DMA_CH5, DMA_INT_HTX | DMA_INT_TXC, ENABLE);
    DMA_EnableChannel(DMA_CH5, ENABLE);

    /* Enable UART5 DMA request */
    USART_EnableDMA(EC800M_UART, USART_DMAREQ_RX, ENABLE);

    USART_Enable(EC800M_UART, ENABLE);
}

/* ── SPI1 Flash (PA5=SCK AF0, PA6=MISO AF0, PA7=MOSI AF0, PA4=CS) ──────── */
void hw_spi_init(void)
{
    GPIO_InitType g;
    SPI_InitType  s;

    RCC_EnableAPB2PeriphClk(FLASH_SPI_CLK, ENABLE);
    GPIO_InitStruct(&g);

    g.GPIO_Mode      = GPIO_Mode_AF_PP;
    g.GPIO_Slew_Rate = GPIO_Slew_Rate_High;
    g.GPIO_Current   = GPIO_DC_4mA;
    g.GPIO_Pull      = GPIO_No_Pull;

    g.Pin            = FLASH_SCK_PIN;
    g.GPIO_Alternate = GPIO_AF0_SPI1;
    GPIO_InitPeripheral(FLASH_SCK_PORT, &g);

    g.Pin            = FLASH_MOSI_PIN;
    g.GPIO_Alternate = GPIO_AF0_SPI1;
    GPIO_InitPeripheral(FLASH_MOSI_PORT, &g);

    g.GPIO_Mode      = GPIO_Mode_Input;
    g.Pin            = FLASH_MISO_PIN;
    g.GPIO_Alternate = GPIO_AF0_SPI1;
    GPIO_InitPeripheral(FLASH_MISO_PORT, &g);

    /* CS already set high by hw_gpio_init */

    SPI_InitStruct(&s);
    s.DataDirection = SPI_DIR_DOUBLELINE_FULLDUPLEX;
    s.SpiMode       = SPI_MODE_MASTER;
    s.DataLen       = SPI_DATA_SIZE_8BITS;
    s.CLKPOL        = SPI_CLKPOL_LOW;
    s.CLKPHA        = SPI_CLKPHA_FIRST_EDGE;
    s.NSS           = SPI_NSS_SOFT;
    s.BaudRatePres  = SPI_BR_PRESCALER_4;       /* 64 MHz / 4 = 16 MHz */
    s.FirstBit      = SPI_FB_MSB;
    s.CRCPoly       = 7;
    SPI_Init(FLASH_SPI, &s);
    SPI_Enable(FLASH_SPI, ENABLE);
}

/* ── I2C2 (PD15=SCL AF6, PD14=SDA AF6) 100 kHz ───────────────────────────── */
void hw_i2c_init(void)
{
    GPIO_InitType g;
    I2C_InitType  i;

    RCC_EnableAPB1PeriphClk(BSP_I2C_CLK, ENABLE);
    GPIO_InitStruct(&g);

    g.Pin = BSP_I2C_SCL_PIN | BSP_I2C_SDA_PIN;
    g.GPIO_Mode = GPIO_Mode_Input;
    g.GPIO_Slew_Rate = GPIO_Slew_Rate_Low;
    g.GPIO_Current = GPIO_DC_4mA;
    g.GPIO_Pull = GPIO_Pull_Up;
    GPIO_InitPeripheral(GPIOD, &g);
    delay_us(10U);
    dbg_printf("[ACCEL] bus pre SCL=%u SDA=%u\r\n",
               GPIO_ReadInputDataBit(BSP_I2C_SCL_PORT, BSP_I2C_SCL_PIN),
               GPIO_ReadInputDataBit(BSP_I2C_SDA_PORT, BSP_I2C_SDA_PIN));

    g.GPIO_Mode      = GPIO_Mode_AF_OD;
    g.GPIO_Slew_Rate = GPIO_Slew_Rate_High;
    g.GPIO_Current   = GPIO_DC_4mA;
    g.GPIO_Pull      = GPIO_Pull_Up;

    g.Pin = BSP_I2C_SCL_PIN;
    g.GPIO_Alternate = BSP_I2C_GPIO_AF;
    GPIO_InitPeripheral(BSP_I2C_SCL_PORT, &g);

    g.Pin = BSP_I2C_SDA_PIN;
    g.GPIO_Alternate = BSP_I2C_GPIO_AF;
    GPIO_InitPeripheral(BSP_I2C_SDA_PORT, &g);

    I2C_DeInit(BSP_I2C);
    I2C_InitStruct(&i);
    i.BusMode     = I2C_BUSMODE_I2C;
    i.FmDutyCycle = I2C_FMDUTYCYCLE_2;
    i.OwnAddr1    = 0x00;
    i.AckEnable   = I2C_ACKEN;
    i.AddrMode    = I2C_ADDR_MODE_7BIT;
    i.ClkSpeed    = 100000;
    I2C_Init(BSP_I2C, &i);
    I2C_Enable(BSP_I2C, ENABLE);
}

/* ── ADC: PA3 (ch4=CAR) PA1 (ch2=BAT) ────────────────────────────────────── */
void hw_adc_init(void)
{
    GPIO_InitType g;
    ADC_InitType  a;

    /* ADC clock is on AHB bus */
    RCC_EnableAHBPeriphClk(RCC_AHB_PERIPH_ADC, ENABLE);
    GPIO_InitStruct(&g);
    g.GPIO_Mode  = GPIO_Mode_Analog;
    g.GPIO_Pull  = GPIO_No_Pull;
    g.Pin = ADC_CAR_PIN | ADC_BAT_PIN;
    GPIO_InitPeripheral(ADC_CAR_PORT, &g);

    ADC_DeInit(ADC);
    ADC_InitStruct(&a);
    a.MultiChEn      = DISABLE;
    a.ContinueConvEn = DISABLE;
    a.ExtTrigSelect  = ADC_EXT_TRIGCONV_NONE;
    a.DatAlign       = ADC_DAT_ALIGN_R;
    a.ChsNumber      = 1;
    ADC_Init(ADC, &a);
    ADC_Enable(ADC, ENABLE);
    ADC_StartCalibration(ADC);
    while (ADC_GetCalibrationStatus(ADC));
}

/* ── TIM8: 1 ms update interrupt ─────────────────────────────────────────── */
void hw_tim_init(void)
{
    TIM_TimeBaseInitType t;

    RCC_EnableAPB2PeriphClk(RCC_APB2_PERIPH_TIM8, ENABLE);
    TIM_InitTimBaseStruct(&t);
    /* APB2 = 64 MHz; prescaler 63 → 1 MHz timer clock; period 999 → 1 ms */
    t.Prescaler = 63;
    t.CntMode   = TIM_CNT_MODE_UP;
    t.Period    = 999;
    t.ClkDiv    = TIM_CLK_DIV1;
    t.RepetCnt  = 0;
    TIM_InitTimeBase(TIM8, &t);
    TIM_ConfigInt(TIM8, TIM_INT_UPDATE, ENABLE);
    TIM_Enable(TIM8, ENABLE);
}

/* ── IWDG ─────────────────────────────────────────────────────────────────── */
void hw_iwdg_init(void)
{
    IWDG_WriteConfig(IWDG_WRITE_ENABLE);
    IWDG_SetPrescalerDiv(IWDG_PRESCALER_DIV256);
    /* LSI ~40 kHz / 256 ≈ 156 Hz; reload 4095 (max) ≈ 26 s timeout.
     * Generous timeout so blocking AT commands during EC800M init
     * (e.g. AT+QIACT can take 10 s) don't trigger a spurious reset. */
    IWDG_CntReload(4095);
    IWDG_WriteConfig(IWDG_WRITE_DISABLE);
    IWDG_Enable();
}

/* ── NVIC ─────────────────────────────────────────────────────────────────── */
void hw_nvic_init(void)
{
    NVIC_PriorityGroupConfig(NVIC_PriorityGroup_2);

    NVIC_InitType n;
    n.NVIC_IRQChannelCmd = ENABLE;

    /* UART4 GPS RX (priority 1) */
    n.NVIC_IRQChannel                   = UART4_IRQn;
    n.NVIC_IRQChannelPreemptionPriority = 1;
    n.NVIC_IRQChannelSubPriority        = 0;
    NVIC_Init(&n);

    /* DMA Channel5 for UART5 RX (priority 1) — based on vendor firmware */
    n.NVIC_IRQChannel                   = DMA_Channel5_IRQn;
    n.NVIC_IRQChannelPreemptionPriority = 1;
    n.NVIC_IRQChannelSubPriority        = 0;
    NVIC_Init(&n);

    /* TIM8 update (priority 2) */
    n.NVIC_IRQChannel                   = TIM8_UP_IRQn;
    n.NVIC_IRQChannelPreemptionPriority = 2;
    n.NVIC_IRQChannelSubPriority        = 0;
    NVIC_Init(&n);
}

/* ── Delays ───────────────────────────────────────────────────────────────── */
void delay_ms(uint32_t ms)
{
    uint32_t start = g_tick_ms;
    while ((g_tick_ms - start) < ms);
}

void delay_us(uint32_t us)
{
    us *= 16;
    while (us--) __NOP();
}
