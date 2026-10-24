#ifndef RTC_LSI_CALIBRATION_H
#define RTC_LSI_CALIBRATION_H
#include <stdint.h>
/* Boot-only TIM9 owner. Internal LSI CH3 capture; no pin remap/IRQ.
 * Returns 0 on failure. Hardware timing requires device/HIL verification. */
uint32_t rtc_lsi_measure_hz(void);
#endif
