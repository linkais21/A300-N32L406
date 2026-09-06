#include "reset_diag.h"
#include "n32l40x_rcc.h"
static reset_reason_t s_reason;
static uint8_t s_raw_flags;
void reset_diag_capture(void){
 /* Several flags can be set at once (a POR that also latched PIN, say), so
  * keep the raw set for the boot banner instead of only the winning reason.
  * The bootloader deliberately leaves these for us -- it used to clear them,
  * which made every boot report "unknown". */
 s_raw_flags = (uint8_t)
   ((RCC_GetFlagStatus(RCC_CTRLSTS_FLAG_IWDGRSTF)==SET?RESET_FLAG_IWDG:0U) |
    (RCC_GetFlagStatus(RCC_CTRLSTS_FLAG_WWDGRSTF)==SET?RESET_FLAG_WWDG:0U) |
    (RCC_GetFlagStatus(RCC_CTRLSTS_FLAG_SFTRSTF)==SET?RESET_FLAG_SOFTWARE:0U) |
    (RCC_GetFlagStatus(RCC_CTRLSTS_FLAG_LPWRRSTF)==SET?RESET_FLAG_LOW_POWER:0U) |
    (RCC_GetFlagStatus(RCC_CTRLSTS_FLAG_PORRSTF)==SET?RESET_FLAG_POWER_ON:0U) |
    (RCC_GetFlagStatus(RCC_CTRLSTS_FLAG_PINRSTF)==SET?RESET_FLAG_PIN:0U));
 if(RCC_GetFlagStatus(RCC_CTRLSTS_FLAG_IWDGRSTF)==SET)s_reason=RESET_REASON_IWDG;
 else if(RCC_GetFlagStatus(RCC_CTRLSTS_FLAG_WWDGRSTF)==SET)s_reason=RESET_REASON_WWDG;
 else if(RCC_GetFlagStatus(RCC_CTRLSTS_FLAG_SFTRSTF)==SET)s_reason=RESET_REASON_SOFTWARE;
 else if(RCC_GetFlagStatus(RCC_CTRLSTS_FLAG_LPWRRSTF)==SET)s_reason=RESET_REASON_LOW_POWER;
 else if(RCC_GetFlagStatus(RCC_CTRLSTS_FLAG_PORRSTF)==SET)s_reason=RESET_REASON_POWER_ON;
 else if(RCC_GetFlagStatus(RCC_CTRLSTS_FLAG_PINRSTF)==SET)s_reason=RESET_REASON_PIN;
 else s_reason=RESET_REASON_UNKNOWN;
 RCC_ClrFlag();
}
reset_reason_t reset_diag_reason(void){return s_reason;}
uint8_t reset_diag_raw_flags(void){return s_raw_flags;}
const char *reset_diag_name(reset_reason_t r){switch(r){case RESET_REASON_IWDG:return "iwdg";case RESET_REASON_WWDG:return "wwdg";case RESET_REASON_SOFTWARE:return "software";case RESET_REASON_PIN:return "pin";case RESET_REASON_POWER_ON:return "power-on";case RESET_REASON_LOW_POWER:return "low-power";default:return "unknown";}}
