#include "relay.h"
#include "config.h"
#include "n32l40x.h"
#include "debug_uart.h"
static volatile bool s_state = false;
static volatile uint16_t s_test_ms;
/* Port of A300's command-time PA11 reclaim to the N32L40x GPIO API.
 * Here true means CUT (the historical A300 relay_set boolean meant RESTORE).
 * Called only by main-loop commands, never by the 1 ms expiry ISR. */
static void relay_gpio_write(bool cut)
{
    GPIO_InitType gpio;
    RCC_EnableAPB2PeriphClk(RCC_APB2_PERIPH_GPIOA, ENABLE);
    /* Preload before enabling output to avoid driving the old latch value. */
    if (cut) GPIO_SetBits(RELAY_PORT, RELAY_PIN);
    else GPIO_ResetBits(RELAY_PORT, RELAY_PIN);
    GPIO_InitStruct(&gpio);
    gpio.Pin = RELAY_PIN;
    gpio.GPIO_Mode = GPIO_Mode_Out_PP;
    gpio.GPIO_Slew_Rate = GPIO_Slew_Rate_High;
    gpio.GPIO_Current = GPIO_DC_12mA;
    gpio.GPIO_Pull = GPIO_No_Pull;
    GPIO_InitPeripheral(RELAY_PORT, &gpio);
}
static void relay_log(void)
{
    dbg_printf("[RELAY] CUT=%u ODR=%u PAD=%u TEST_MS=%u\r\n",
               (unsigned)s_state,
               (unsigned)GPIO_ReadOutputDataBit(RELAY_PORT, RELAY_PIN),
               (unsigned)GPIO_ReadInputDataBit(RELAY_PORT, RELAY_PIN),
               (unsigned)s_test_ms);
}
static uint32_t lock(void)
{
#if defined(__arm__) || defined(__thumb__)
    uint32_t mask = __get_PRIMASK();
    __disable_irq();
    return mask;
#else
    return 0U;
#endif
}
static void unlock(uint32_t mask)
{
#if defined(__arm__) || defined(__thumb__)
    __set_PRIMASK(mask);
#else
    (void)mask;
#endif
}
void relay_set(bool on)
{
    uint32_t mask = lock();
    /* A business request must never extend an active production pulse. */
    if (on && s_test_ms != 0U) { unlock(mask); return; }
    s_test_ms = 0U;
    s_state = on;
    relay_gpio_write(on);
    unlock(mask);
    relay_log();
}
bool relay_get(void) { return s_state; }
bool relay_test_low(void)
{
    uint32_t mask = lock();
    bool ready = !s_state && s_test_ms == 0U;
    if (ready) {
        s_test_ms = 3000U;
        s_state = true;
        relay_gpio_write(true);
    }
    unlock(mask);
    if (ready) relay_log();
    return ready;
}
void relay_test_high(void) { relay_set(false); }
uint16_t relay_test_remaining(void) { return s_test_ms; }
void relay_test_tick(void)
{
    if (s_test_ms != 0U && --s_test_ms == 0U) {
        GPIO_ResetBits(RELAY_PORT, RELAY_PIN);
        s_state = false;
    }
}
