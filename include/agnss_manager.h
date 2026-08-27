#ifndef AGNSS_MANAGER_H
#define AGNSS_MANAGER_H
#include <stdbool.h>
#include <stdint.h>
#include "agnss_storage.h"
void agnss_init(gnss_type_t type);
typedef bool (*agnss_inject_cb_t)(gnss_type_t type, const uint8_t *data, uint16_t len);
void agnss_set_inject_callback(agnss_inject_cb_t cb);
void agnss_process(void);
bool agnss_has_injected(void);
bool agnss_retry_due(uint32_t now_ms);
#endif
