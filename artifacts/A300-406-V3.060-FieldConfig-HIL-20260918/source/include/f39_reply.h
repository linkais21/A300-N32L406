#ifndef F39_REPLY_H
#define F39_REPLY_H

#include <stdbool.h>
#include <stdint.h>

#include "f39_config_adapter.h"

#define F39_REPLY_MAX_LENGTH 256U
#define F39_RESET_DELAY_MS   100U
#define F39_VERSION_MAX_LENGTH 63U
#define F39_IMEI_MAX_LENGTH    15U
#define F39_ICCID_MAX_LENGTH   20U

typedef struct {
    uint16_t len;
    uint8_t data[F39_REPLY_MAX_LENGTH];
    bool reset_pending;
    uint32_t reset_delay_ms;
} f39_reply_t;

typedef void (*f39_effect_fn)(void *context);
typedef void (*f39_auth_reset_fn)(uint8_t channel_mask, void *context);
typedef void (*f39_gnss_mode_fn)(gnss_type_t receiver, uint8_t mode,
                                 void *context);
typedef bool (*f39_relay_fn)(bool cut, void *context);
typedef bool (*f39_gps_valid_fn)(void *context);
typedef float (*f39_gps_speed_fn)(void *context);

/* Platform services are injected so command execution remains host-testable. */
typedef struct {
    device_config_t *config;
    f39_persist_config_fn persist;
    void *context;
    f39_effect_fn timer_refresh;
    f39_effect_fn network_reconnect;
    f39_auth_reset_fn jt808_auth_reset;
    f39_effect_fn modem_pdp_restart;
    f39_gnss_mode_fn gnss_set_mode;
    f39_effect_fn jt808_reregister;
    f39_effect_fn remaining_refresh;
    f39_effect_fn fota_recheck;
    f39_relay_fn relay_set;
    f39_gps_valid_fn gps_valid;
    f39_gps_speed_fn gps_speed_kmh;
    bool (*relay_get)(void *context);
    const char *version;
    uint16_t version_len;
    const char *imei;
    uint16_t imei_len;
    const char *iccid;
    uint16_t iccid_len;
    int csq;
    bool acc_on;
    uint8_t gps_fix_quality;
    uint8_t gps_satellites;
    uint16_t gps_hdop_x10;
} f39_platform_t;

f39_result_t f39_execute(const f39_request_t *request,
                         f39_platform_t *platform,
                         f39_reply_t *reply);

/* Commit first, acknowledge on the existing transport, then apply effects. */
f39_result_t f39_execute_deferred(const f39_request_t *request,
                                 f39_platform_t *platform,
                                 f39_reply_t *reply, uint32_t *effects);
void f39_apply_effects(uint32_t effects, f39_platform_t *platform);

#endif /* F39_REPLY_H */
