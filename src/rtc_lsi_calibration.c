#include "rtc_lsi_calibration.h"
#include "config.h"
#include "n32l40x_tim.h"
#include "n32l40x_rcc.h"

uint32_t rtc_lsi_measure_hz(void)
{
    uint32_t sum = 0U, frequency = 0U;
    uint16_t previous = 0U;
    unsigned count = 0U;
    /* SystemCoreClock is HCLK. APB DIV1/DIV2 both clock the timer at HCLK;
     * DIV4/8/16 clock it at HCLK/2/4/8 (APB timer x2 rule). */
    uint32_t timer_hz = SystemCoreClock;
    uint32_t divider = (RCC->CFG & RCC_CFG_APB1PRES) >> 8U;
    if (divider >= 4U) timer_hz >>= divider - 4U;
    if (timer_hz < 1000000U || timer_hz % 1000000U != 0U) return 0U;
    RCC_EnableAPB1PeriphClk(RCC_APB1_PERIPH_TIM9, ENABLE);
    TIM_DeInit(TIM9);
    TIM_ConfigPrescaler(TIM9, timer_hz / 1000000U - 1U,
                        TIM_PSC_RELOAD_MODE_IMMEDIATE);
    /* Dedicated CH3 rising/direct input, capture every eight edges, no filter.
     * Equivalent to the vendor TIM_ICInit/TIM_SetInCapPrescaler sequence. */
    TIM9->CCMOD2 = TIM_CCMOD2_CC3SEL_0 | TIM_IC_PSC_DIV8;
    TIM9->CCEN = TIM_CCEN_CC3EN;
    /* Vendor IWDG_Reset example: C3SEL internally connects LSI to TIM9.
     * External PB14 remap and capture IRQ are intentionally unnecessary. */
    TIM9->CTRL1 |= TIM_CTRL1_C3SEL;
    TIM9->STS = 0U;
    TIM_Enable(TIM9, ENABLE);
    uint32_t started = TICK_MS();
    for (uint32_t polls = 0U; polls < 200000U &&
         (uint32_t)(TICK_MS() - started) < 50U; ++polls) {
        if (TIM_GetFlagStatus(TIM9, TIM_FLAG_CC3OF) != RESET) break;
        if (TIM_GetFlagStatus(TIM9, TIM_FLAG_CC3) == RESET) continue;
        uint16_t capture = TIM_GetCap3(TIM9);
        TIM_ClrIntPendingBit(TIM9, TIM_INT_CC3);
        if (count != 0U) {
            uint16_t delta = (uint16_t)(capture - previous);
            if (delta < 100U || delta > 400U) break; /* 20..80 kHz */
            sum += delta;
        }
        previous = capture;
        if (++count == 65U) {
            frequency = (512000000U + sum / 2U) / sum;
            break;
        }
    }
    TIM_DeInit(TIM9);
    RCC_EnableAPB1PeriphClk(RCC_APB1_PERIPH_TIM9, DISABLE);
    return frequency;
}
