#ifndef AGNSS_MANAGER_H
#define AGNSS_MANAGER_H
#include <stdbool.h>
#include <stdint.h>
#include "agnss_storage.h"
void agnss_init(gnss_type_t type);
void agnss_process(void);
bool agnss_has_injected(void);
bool agnss_retry_due(uint32_t now_ms);
#endif
