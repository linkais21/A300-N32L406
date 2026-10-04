#ifndef F39_PRODUCTION_BINDINGS_H
#define F39_PRODUCTION_BINDINGS_H

#include "f39_reply.h"

bool f39_production_persist(const device_config_t *candidate, void *context);
void f39_production_timer_refresh(void *context);
void f39_production_network_reconnect(void *context);
void f39_production_jt808_auth_reset(uint8_t channel_mask, void *context);
void f39_production_modem_pdp_restart(void *context);
void f39_production_gnss_set_mode(gnss_type_t type, uint8_t mode, void *context);
void f39_production_jt808_reregister(void *context);
void f39_production_remaining_refresh(void *context);
void f39_production_fota_recheck(void *context);
bool f39_production_relay_set(bool cut, void *context);
bool f39_production_gps_valid(void *context);
float f39_production_gps_speed_kmh(void *context);
bool f39_production_relay_get(void *context);

#endif
