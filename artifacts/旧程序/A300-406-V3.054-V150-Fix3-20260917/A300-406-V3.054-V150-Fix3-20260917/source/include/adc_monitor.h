#ifndef ADC_MONITOR_H
#define ADC_MONITOR_H

#include <stdint.h>
#include <stdbool.h>

void  adc_monitor_init(void);
void  adc_monitor_process(void);   /* call from main loop */
bool  adc_monitor_valid(void);     /* both conversions succeeded recently */

float adc_get_car_voltage(void);   /* vehicle supply voltage */
float adc_get_bat_voltage(void);   /* internal battery voltage */
bool  adc_is_car_powered(void);    /* > 9 V */
bool  adc_is_bat_low(void);        /* < 3.5 V */

#endif
