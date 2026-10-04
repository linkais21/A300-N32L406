#ifndef AGNSS_ONLINE_H
#define AGNSS_ONLINE_H
#include "agnss_storage.h"
void agnss_online_reset(void);
bool agnss_online_process(gnss_type_t type);
void agnss_online_rx(uint8_t channel, const uint8_t *data, uint16_t length);
bool agnss_online_has_injected(void);
#endif
