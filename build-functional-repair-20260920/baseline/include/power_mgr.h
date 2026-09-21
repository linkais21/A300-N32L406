#ifndef POWER_MGR_H
#define POWER_MGR_H

#include <stdint.h>
#include <stdbool.h>
#include "work_mode_sleep.h"

typedef enum {
    WAKE_SRC_NONE      = 0,
    WAKE_SRC_RTC       = (1 << 0),
    WAKE_SRC_LIGHT     = (1 << 2),
    WAKE_SRC_ACC       = (1 << 3),
    WAKE_SRC_SOS       = (1 << 4),
    WAKE_SRC_CHARGE    = (1 << 5),
    WAKE_SRC_GPRS      = (1 << 6),
} wake_src_t;

void        pwr_init(void);
void        pwr_wake(wake_src_t src);    /* force wake from ISR or event */

/* Called from EXTI handlers */
void pwr_acc_isr(void);
void pwr_sos_isr(void);
void pwr_charge_isr(void);
void pwr_light_isr(void);

#define WORK_MODE_SLEEP_LEGACY_POWER_MGR 1

#endif
