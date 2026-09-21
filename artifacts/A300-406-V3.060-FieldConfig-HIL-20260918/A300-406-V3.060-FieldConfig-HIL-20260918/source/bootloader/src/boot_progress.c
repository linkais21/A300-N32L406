#include "image_install.h"
#include "n32l40x.h"
#include "n32l40x_usart.h"
#include "n32l40x_gpio.h"
#include "n32l40x_rcc.h"

static bool initialized, failed;

static bool put(char c)
{
    uint32_t budget = 64000U;
    if (failed) return false;
    while (USART_GetFlagStatus(USART1, USART_FLAG_TXDE) == RESET) {
        boot_watchdog_feed();
        if (--budget == 0U) { failed = true; return false; }
    }
    USART_SendData(USART1, (uint8_t)c);
    return true;
}

static void text(const char *s) { while (*s && put(*s)) ++s; }
static void number(uint32_t n)
{
    char digits[10]; unsigned count = 0;
    do { digits[count++] = (char)('0' + n % 10U); n /= 10U; } while (n);
    while (count && put(digits[--count])) { }
}

static void uart_init(void)
{
    if (!initialized) {
        GPIO_InitType g; USART_InitType u;
        RCC_EnableAPB2PeriphClk(RCC_APB2_PERIPH_GPIOA | RCC_APB2_PERIPH_USART1, ENABLE);
        GPIO_InitStruct(&g);
        g.Pin = GPIO_PIN_9; g.GPIO_Mode = GPIO_Mode_AF_PP;
        g.GPIO_Alternate = GPIO_AF4_USART1; g.GPIO_Current = GPIO_DC_4mA;
        g.GPIO_Slew_Rate = GPIO_Slew_Rate_High; g.GPIO_Pull = GPIO_No_Pull;
        GPIO_InitPeripheral(GPIOA, &g);
        USART_StructInit(&u); u.BaudRate = 115200;
        u.Mode = USART_MODE_TX;
        USART_Init(USART1, &u); USART_Enable(USART1, ENABLE);
        initialized = true;
    }
}

void boot_install_progress(uint32_t done, uint32_t total, bool complete)
{
    if (failed || !total || done > total) return;
    uart_init();
    text("[FOTA] install progress="); number(done * 100U / total);
    text("% bytes="); number(done); text("/"); number(total);
    text(complete ? " state=trial-ready\r\n" : " state=writing\r\n");
    /* Drain the final byte before a possible App jump. UART failure is diagnostic only. */
    uint32_t budget = 64000U;
    while (!failed && USART_GetFlagStatus(USART1, USART_FLAG_TXC) == RESET) {
        boot_watchdog_feed();
        if (--budget == 0U) failed = true;
    }
}

void boot_startup_status(const char *stage, int32_t value)
{
    if (failed) return;
    uart_init();
    text("[BOOT] "); text(stage); text("=");
    if (value < 0) { put('-'); number(0U - (uint32_t)value); }
    else number((uint32_t)value);
    text("\r\n");
    uint32_t budget = 64000U;
    while (!failed && USART_GetFlagStatus(USART1, USART_FLAG_TXC) == RESET) {
        boot_watchdog_feed();
        if (--budget == 0U) failed = true;
    }
}
