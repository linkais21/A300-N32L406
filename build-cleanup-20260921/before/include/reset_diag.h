#ifndef A300_RESET_DIAG_H
#define A300_RESET_DIAG_H
#include <stdint.h>
#include <stdbool.h>
typedef enum { RESET_REASON_UNKNOWN=0, RESET_REASON_IWDG, RESET_REASON_WWDG,
 RESET_REASON_SOFTWARE, RESET_REASON_PIN, RESET_REASON_POWER_ON,
 RESET_REASON_LOW_POWER } reset_reason_t;
/* Raw flag bits, reported alongside the decoded reason because more than one
 * can be latched by a single reset. */
#define RESET_FLAG_IWDG       0x01U
#define RESET_FLAG_WWDG       0x02U
#define RESET_FLAG_SOFTWARE   0x04U
#define RESET_FLAG_LOW_POWER  0x08U
#define RESET_FLAG_POWER_ON   0x10U
#define RESET_FLAG_PIN        0x20U

#define RESET_DIAG_BACKUP_WORDS 8U
/* Word indexes are public for the host NOR/backup emulation harness. */
#define RESET_DIAG_WORD_PHASE  1U

typedef enum {
    RESET_DIAG_PHASE_BOOT = 0,
    RESET_DIAG_PHASE_EC800M,
    RESET_DIAG_PHASE_GPS,
    RESET_DIAG_PHASE_MILEAGE,
    RESET_DIAG_PHASE_TCP_MANAGER,
    RESET_DIAG_PHASE_JT808,
    RESET_DIAG_PHASE_ADC,
    RESET_DIAG_PHASE_GEOFENCE, /* Reserved for historical diagnostic records. */
    RESET_DIAG_PHASE_FOTA,
    RESET_DIAG_PHASE_BLIND_ZONE,
    RESET_DIAG_PHASE_LOG_PLATFORM,
    RESET_DIAG_PHASE_CONFIG,
    RESET_DIAG_PHASE_AGNSS,
    RESET_DIAG_PHASE_WORK_MODE,
    RESET_DIAG_PHASE_AT_CONFIG,
    RESET_DIAG_PHASE_SMS,
    RESET_DIAG_PHASE_ALARMS,
    RESET_DIAG_PHASE_NTP,
    RESET_DIAG_PHASE_STATUS,
    RESET_DIAG_PHASE_IDLE_SLEEP,
} reset_diag_phase_t;

typedef struct {
    reset_diag_phase_t phase;
    uint32_t loop_sequence;
    bool hardfault;
    uint32_t pc;
    uint32_t lr;
    uint32_t cfsr;
    uint32_t hfsr;
} reset_diag_snapshot_t;

void reset_diag_capture(void);
void reset_diag_runtime_init(void);
void reset_diag_loop_begin(void);
void reset_diag_mark_phase(reset_diag_phase_t phase);
void reset_diag_record_fault(uint32_t pc, uint32_t lr,
                             uint32_t cfsr, uint32_t hfsr);
bool reset_diag_previous(reset_diag_snapshot_t *out);
reset_reason_t reset_diag_reason(void);
uint8_t reset_diag_raw_flags(void);
const char *reset_diag_name(reset_reason_t reason);
const char *reset_diag_phase_name(reset_diag_phase_t phase);

#ifdef RESET_DIAG_HOST_TEST
uint32_t reset_diag_host_backup_read(uint8_t index);
void reset_diag_host_backup_write(uint8_t index, uint32_t value);
uint8_t reset_diag_host_reset_flags(void);
void reset_diag_host_clear_reset_flags(void);
void reset_diag_host_enable_backup_access(void);
#endif
#endif
