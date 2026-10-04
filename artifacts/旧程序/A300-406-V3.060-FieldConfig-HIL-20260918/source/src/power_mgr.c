#include "power_mgr.h"
#include "config.h"
#include "n32l40x.h"

/* Compatibility routing only; work_mode_sleep owns the policy. */
#define WORK_MODE_SLEEP_LEGACY_POWER_MGR 1

static volatile wake_src_t s_wake;

void pwr_init(void)
{
    RCC_EnableAPB2PeriphClk(RCC_APB2_PERIPH_AFIO, ENABLE);
    s_wake = WAKE_SRC_NONE;
    work_mode_sleep_init();
}

void pwr_process(void)
{
    work_sleep_wake_t wake = work_mode_sleep_take_wake();
    if (wake != WORK_SLEEP_WAKE_NONE)
        work_mode_sleep_process(1000U, wake);
}

pwr_state_t pwr_get_state(void)
{
    return work_mode_sleep_is_in_stop1() ? PWR_STATE_DEEP_SLEEP : PWR_STATE_ACTIVE;
}

void pwr_request_sleep(void)
{
    work_mode_sleep_process(15000U, WORK_SLEEP_WAKE_NONE);
}

void pwr_wake(wake_src_t src)
{
    s_wake |= src;
    if ((src & WAKE_SRC_ACC) != 0) work_mode_sleep_isr_wake(WORK_SLEEP_WAKE_ACC);
    if ((src & WAKE_SRC_SOS) != 0) work_mode_sleep_isr_wake(WORK_SLEEP_WAKE_SOS);
    if ((src & (WAKE_SRC_CHARGE | WAKE_SRC_LIGHT)) != 0)
        work_mode_sleep_isr_wake(WORK_SLEEP_WAKE_POWER);
}

void pwr_acc_isr(void) { pwr_wake(WAKE_SRC_ACC); }
void pwr_sos_isr(void) { pwr_wake(WAKE_SRC_SOS); }
void pwr_charge_isr(void) { pwr_wake(WAKE_SRC_CHARGE); }
void pwr_light_isr(void) { pwr_wake(WAKE_SRC_LIGHT); }

void EXTI0_IRQHandler(void)
{
    if (EXTI_GetITStatus(EXTI_LINE0)) {
        EXTI_ClrITPendBit(EXTI_LINE0);
        pwr_light_isr();
    }
}

void EXTI2_IRQHandler(void)
{
    if (EXTI_GetITStatus(EXTI_LINE2)) {
        EXTI_ClrITPendBit(EXTI_LINE2);
        pwr_sos_isr();
    }
}

void EXTI15_10_IRQHandler(void)
{
    if (EXTI_GetITStatus(EXTI_LINE12)) {
        EXTI_ClrITPendBit(EXTI_LINE12);
        pwr_acc_isr();
    }
    if (EXTI_GetITStatus(EXTI_LINE15)) {
        EXTI_ClrITPendBit(EXTI_LINE15);
        pwr_charge_isr();
    }
}
