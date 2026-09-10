#ifndef WORK_MODE_SLEEP_H
#define WORK_MODE_SLEEP_H

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    WORK_SLEEP_WAKE_NONE = 0,
    WORK_SLEEP_WAKE_RTC = 1u << 0,
    WORK_SLEEP_WAKE_ACC = 1u << 1,
    WORK_SLEEP_WAKE_VIBRATION = 1u << 2,
    WORK_SLEEP_WAKE_SOS = 1u << 3,
    WORK_SLEEP_WAKE_POWER = 1u << 4
} work_sleep_wake_t;

void work_mode_sleep_init(void);
bool work_mode_sleep_ready(void);
void work_mode_sleep_process(uint32_t next_service_ms, work_sleep_wake_t pending_wake);
/* Shallow sleep window, matching the validated reference profile.
 *
 * SysTick, TIM8 and the modem UART/DMA stay enabled, so WFI returns on the
 * next 1 ms tick and the main loop re-polls PA12 through work_mode_process().
 * ACC detection therefore no longer depends on catching the EXTI edge: the
 * 50 ms WORK_MODE_ACC_DEBOUNCE_MS window advances on real time because
 * TICK_MS() keeps running, so a level that arrived while asleep commits
 * within ~50 ms instead of waiting for the next RTC slice.
 *
 * This trades STOP1's microamp floor for that response time -- the device is
 * awake for a far larger fraction of each second. Use work_mode_sleep_process()
 * instead when the power budget matters more than ACC latency. */
void work_mode_sleep_shallow(void);
work_sleep_wake_t work_mode_sleep_take_wake(void);
void work_mode_sleep_isr_wake(work_sleep_wake_t source);
bool work_mode_sleep_is_in_stop1(void);
uint32_t work_mode_sleep_monotonic_s(void);

#endif
