#ifndef WORK_MODE_H
#define WORK_MODE_H

#include <stdbool.h>
#include <stdint.h>
#include "flash_config.h"

typedef enum {
    WORK_MODE_BOOT_MONITOR,
    WORK_MODE_REALTIME,
    WORK_MODE_STATIONARY_SLEEP
} work_mode_state_t;

typedef struct {
    uint16_t report_moving_s;
    uint16_t report_stopped_s;
    uint16_t heartbeat_s;
    uint32_t stationary_timeout_s;
    uint32_t vibration_confirm_s;
} work_mode_config_t;

typedef struct {
    uint32_t now_s;
    bool acc_high;
    bool vibration_hit;
    bool rtc_wake;
    uint32_t alarm_bits;
    bool gps_valid;
    bool vibration_sample_valid;
    uint32_t now_ms;
} work_mode_input_t;

#define WORK_MODE_ACC_DEBOUNCE_MS 500U
#define WORK_MODE_DEFAULT_STOPPED_REPORT_S 300U

/* Supply the raw PA12 sample and millisecond timestamp before work_mode_step.
 * Host callers that only have second resolution may omit this call. */
void work_mode_acc_sample(bool raw_high, uint32_t now_ms);

typedef enum {
    WORK_ACTION_NONE,
    WORK_ACTION_SET_LOGICAL_ACC,
    WORK_ACTION_GPS_ON,
    WORK_ACTION_GPS_OFF,
    WORK_ACTION_REPORT_ENTRY,
    WORK_ACTION_REPORT_LOCATION,
    WORK_ACTION_REPORT_HEARTBEAT,
    WORK_ACTION_REPORT_ALARM,
    WORK_ACTION_ENTER_STOP1
} work_mode_action_type_t;

typedef struct {
    uint32_t alarm_bits;
    /* RAM-only identity: preserved on retry, renewed for a merged report.
     * Group word fields before enum/bools to preserve the ARM action size. */
    uint32_t report_id;
    work_mode_action_type_t type;
    bool acc_on;
    bool historical_position;
} work_mode_action_t;

uint32_t work_mode_allocate_report_id(void);

void work_mode_init(const work_mode_config_t *cfg, uint32_t now_s, bool acc_high);
void work_mode_configure(const work_mode_config_t *cfg, uint32_t now_s);
void work_mode_step(const work_mode_input_t *input);
bool work_mode_next_action(work_mode_action_t *out);
work_mode_state_t work_mode_state(void);
bool work_mode_logical_acc(void);
/* Vibration confirmation-window progress, for the diagnostic log only: how
 * many samples have been accumulated and how many the window requires. Lets a
 * field capture show that a wake fired but the episode never confirmed. */
uint16_t work_mode_vibration_hits(void);
uint16_t work_mode_vibration_required(void);
void work_mode_config_changed(const device_config_t *cfg, uint32_t now_s);
void work_mode_set_stationary_location_enabled(bool enabled, uint32_t now_s);
void work_mode_notify_alarm(uint32_t alarm_bits);
uint32_t work_mode_take_alarm(void);
void work_mode_process(void);
void work_mode_retry_action(const work_mode_action_t *action);

#endif
