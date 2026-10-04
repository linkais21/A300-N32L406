#ifndef AGNSS_VENDOR_H
#define AGNSS_VENDOR_H

#include <stdint.h>
#include <stdbool.h>
#include "agnss_storage.h"
#include "gps.h"

typedef struct {
    const uint8_t *data;
    uint32_t len;
} agnss_source_t;

int agnss_huada_inject(const agnss_source_t *src, const gps_context_t *ctx);
bool gnss_vendor_inject(gnss_type_t type, const uint8_t *data, uint16_t len);
/* False may mean that the current source chunk is waiting for a module ACK. */
bool gnss_vendor_inject_pending(void);
void gnss_vendor_set_type(gnss_type_t type);
bool gnss_vendor_network_rx(uint8_t ch, const uint8_t *data, uint16_t len);


#endif
