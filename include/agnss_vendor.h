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
int agnss_zhongkewei_request(const agnss_source_t *src, const gps_context_t *ctx);
int gnss_vendor_inject(gnss_type_t type, const uint8_t *data, uint16_t len);

/* Host/transport helpers for Zhongkewei protocol. */
int zhongkewei_build_request(char *out, uint32_t cap, const char *user,
                             const char *pwd, const gps_context_t *ctx);
int zhongkewei_parse_response(const uint8_t *buf, uint32_t len,
                              const uint8_t **payload, uint16_t *payload_len);

#endif
