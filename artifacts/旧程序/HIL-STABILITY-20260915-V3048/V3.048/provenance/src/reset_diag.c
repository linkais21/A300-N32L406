#include "reset_diag.h"
#include <string.h>
#ifndef RESET_DIAG_HOST_TEST
#include "n32l40x_rcc.h"
#include "n32l40x_pwr.h"
#include "n32l40x.h"
#endif

#define RESET_DIAG_MAGIC 0x52444732UL

static reset_reason_t s_reason;
static uint8_t s_raw_flags;
static reset_diag_snapshot_t s_previous;
static bool s_previous_valid;
static uint32_t s_loop_sequence;

static uint32_t backup_read(uint8_t index)
{
#ifdef RESET_DIAG_HOST_TEST
    return reset_diag_host_backup_read(index);
#else
    volatile uint32_t *const words = &RTC->BKP13R;
    return words[index];
#endif
}

static void backup_write(uint8_t index, uint32_t value)
{
#ifdef RESET_DIAG_HOST_TEST
    reset_diag_host_backup_write(index, value);
#else
    volatile uint32_t *const words = &RTC->BKP13R;
    words[index] = value;
#endif
}

static void backup_enable(void)
{
#ifdef RESET_DIAG_HOST_TEST
    reset_diag_host_enable_backup_access();
#else
    RCC_EnableAPB1PeriphClk(RCC_APB1_PERIPH_PWR, ENABLE);
    PWR_BackupAccessEnable(ENABLE);
#endif
}

static uint8_t read_reset_flags(void)
{
#ifdef RESET_DIAG_HOST_TEST
    return reset_diag_host_reset_flags();
#else
    return (uint8_t)
      ((RCC_GetFlagStatus(RCC_CTRLSTS_FLAG_IWDGRSTF)==SET?RESET_FLAG_IWDG:0U) |
       (RCC_GetFlagStatus(RCC_CTRLSTS_FLAG_WWDGRSTF)==SET?RESET_FLAG_WWDG:0U) |
       (RCC_GetFlagStatus(RCC_CTRLSTS_FLAG_SFTRSTF)==SET?RESET_FLAG_SOFTWARE:0U) |
       (RCC_GetFlagStatus(RCC_CTRLSTS_FLAG_LPWRRSTF)==SET?RESET_FLAG_LOW_POWER:0U) |
       (RCC_GetFlagStatus(RCC_CTRLSTS_FLAG_PORRSTF)==SET?RESET_FLAG_POWER_ON:0U) |
       (RCC_GetFlagStatus(RCC_CTRLSTS_FLAG_PINRSTF)==SET?RESET_FLAG_PIN:0U));
#endif
}

static void clear_reset_flags(void)
{
#ifdef RESET_DIAG_HOST_TEST
    reset_diag_host_clear_reset_flags();
#else
    RCC_ClrFlag();
#endif
}

static bool pair_valid(uint32_t word)
{
    uint16_t value = (uint16_t)word;
    uint16_t inverse = (uint16_t)(word >> 16);
    return (uint16_t)~value == inverse;
}

static bool backup_decode(reset_diag_snapshot_t *out)
{
    uint32_t magic = backup_read(0U);
    uint32_t phase = backup_read(1U);
    uint32_t fault = backup_read(3U);
    if (magic != RESET_DIAG_MAGIC || !pair_valid(phase) || !pair_valid(fault))
        return false;
    if ((uint16_t)phase >= (uint16_t)RESET_DIAG_PHASE_IDLE_SLEEP + 1U)
        return false;
    out->phase = (reset_diag_phase_t)(uint16_t)phase;
    out->loop_sequence = backup_read(2U);
    out->hardfault = (uint16_t)fault != 0U;
    out->pc = backup_read(4U);
    out->lr = backup_read(5U);
    out->cfsr = backup_read(6U);
    out->hfsr = backup_read(7U);
    return true;
}

static void backup_commit(void)
{
    /* The magic word is the commit marker and is written last. */
    backup_write(0U, RESET_DIAG_MAGIC);
}

void reset_diag_capture(void){
 /* Several flags can be set at once (a POR that also latched PIN, say), so
  * keep the raw set for the boot banner instead of only the winning reason.
  * The bootloader deliberately leaves these for us -- it used to clear them,
  * which made every boot report "unknown". */
 s_raw_flags = read_reset_flags();
#ifndef RESET_DIAG_HOST_TEST
 if(RCC_GetFlagStatus(RCC_CTRLSTS_FLAG_IWDGRSTF)==SET)s_reason=RESET_REASON_IWDG;
 else if(RCC_GetFlagStatus(RCC_CTRLSTS_FLAG_WWDGRSTF)==SET)s_reason=RESET_REASON_WWDG;
 else if(RCC_GetFlagStatus(RCC_CTRLSTS_FLAG_SFTRSTF)==SET)s_reason=RESET_REASON_SOFTWARE;
 else if(RCC_GetFlagStatus(RCC_CTRLSTS_FLAG_LPWRRSTF)==SET)s_reason=RESET_REASON_LOW_POWER;
 else if(RCC_GetFlagStatus(RCC_CTRLSTS_FLAG_PORRSTF)==SET)s_reason=RESET_REASON_POWER_ON;
 else if(RCC_GetFlagStatus(RCC_CTRLSTS_FLAG_PINRSTF)==SET)s_reason=RESET_REASON_PIN;
 else s_reason=RESET_REASON_UNKNOWN;
 #else
 if (s_raw_flags & RESET_FLAG_IWDG) s_reason = RESET_REASON_IWDG;
 else if (s_raw_flags & RESET_FLAG_WWDG) s_reason = RESET_REASON_WWDG;
 else if (s_raw_flags & RESET_FLAG_SOFTWARE) s_reason = RESET_REASON_SOFTWARE;
 else if (s_raw_flags & RESET_FLAG_LOW_POWER) s_reason = RESET_REASON_LOW_POWER;
 else if (s_raw_flags & RESET_FLAG_POWER_ON) s_reason = RESET_REASON_POWER_ON;
 else if (s_raw_flags & RESET_FLAG_PIN) s_reason = RESET_REASON_PIN;
 else s_reason = RESET_REASON_UNKNOWN;
 #endif
 clear_reset_flags();
}

void reset_diag_runtime_init(void)
{
    backup_enable();
    memset(&s_previous, 0, sizeof s_previous);
    s_previous_valid = backup_decode(&s_previous);
    s_loop_sequence = 0U;
    backup_write(0U, 0U);
    backup_write(1U, (uint32_t)RESET_DIAG_PHASE_BOOT |
                       ((uint32_t)(uint16_t)~(uint16_t)RESET_DIAG_PHASE_BOOT << 16));
    backup_write(2U, 0U);
    backup_write(3U, 0U | ((uint32_t)0xffffU << 16));
    backup_write(4U, 0U);
    backup_write(5U, 0U);
    backup_write(6U, 0U);
    backup_write(7U, 0U);
    backup_commit();
}

void reset_diag_loop_begin(void)
{
    ++s_loop_sequence;
    backup_write(2U, s_loop_sequence);
}

void reset_diag_mark_phase(reset_diag_phase_t phase)
{
    if ((uint16_t)phase > (uint16_t)RESET_DIAG_PHASE_IDLE_SLEEP)
        return;
    /* One aligned peripheral write is atomic. Keep the commit marker valid so
     * an IWDG reset cannot land in an artificial invalid-record window. */
    backup_write(1U, (uint32_t)(uint16_t)phase |
                       ((uint32_t)(uint16_t)~(uint16_t)phase << 16));
}

void reset_diag_record_fault(uint32_t pc, uint32_t lr,
                             uint32_t cfsr, uint32_t hfsr)
{
    backup_write(0U, 0U);
    backup_write(3U, 1U | ((uint32_t)0xfffeU << 16));
    backup_write(4U, pc);
    backup_write(5U, lr);
    backup_write(6U, cfsr);
    backup_write(7U, hfsr);
    backup_commit();
}

bool reset_diag_previous(reset_diag_snapshot_t *out)
{
    if (out == NULL || !s_previous_valid) return false;
    *out = s_previous;
    return true;
}
reset_reason_t reset_diag_reason(void){return s_reason;}
uint8_t reset_diag_raw_flags(void){return s_raw_flags;}
const char *reset_diag_name(reset_reason_t r){switch(r){case RESET_REASON_IWDG:return "iwdg";case RESET_REASON_WWDG:return "wwdg";case RESET_REASON_SOFTWARE:return "software";case RESET_REASON_PIN:return "pin";case RESET_REASON_POWER_ON:return "power-on";case RESET_REASON_LOW_POWER:return "low-power";default:return "unknown";}}
const char *reset_diag_phase_name(reset_diag_phase_t phase)
{
    static const char *const names[] = {
        "boot", "ec800m", "gps", "mileage", "tcp", "jt808", "adc",
        "geofence", "fota", "blind-zone", "log-platform", "config",
        "agnss", "work-mode", "at-config", "sms", "alarms", "ntp",
        "status", "idle-sleep"
    };
    return (unsigned)phase < sizeof(names) / sizeof(names[0]) ?
           names[phase] : "unknown";
}
