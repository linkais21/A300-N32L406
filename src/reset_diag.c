#include "reset_diag.h"
#include "n32l40x_rcc.h"
static reset_reason_t s_reason;
void reset_diag_capture(void){
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
const char *reset_diag_name(reset_reason_t r){switch(r){case RESET_REASON_IWDG:return "iwdg";case RESET_REASON_WWDG:return "wwdg";case RESET_REASON_SOFTWARE:return "software";case RESET_REASON_PIN:return "pin";case RESET_REASON_POWER_ON:return "power-on";case RESET_REASON_LOW_POWER:return "low-power";default:return "unknown";}}
