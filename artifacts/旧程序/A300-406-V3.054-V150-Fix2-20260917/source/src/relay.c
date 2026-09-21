#include "relay.h"
#include "config.h"
#include "n32l40x.h"
static volatile bool s_state = false;
static volatile uint16_t s_test_ms;
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
    if (on) GPIO_SetBits(RELAY_PORT, RELAY_PIN);
    else    GPIO_ResetBits(RELAY_PORT, RELAY_PIN);
    unlock(mask);
}
bool relay_get(void) { return s_state; }
bool relay_test_low(void)
{
    uint32_t mask = lock();
    bool ready = !s_state && s_test_ms == 0U;
    if (ready) {
        s_test_ms = 3000U;
        s_state = true;
        GPIO_SetBits(RELAY_PORT, RELAY_PIN);
    }
    unlock(mask);
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
