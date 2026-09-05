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
typedef enum { ZK_RESP_MALFORMED=-1, ZK_RESP_INCOMPLETE=0, ZK_RESP_OK=1 } zhongkewei_resp_t;

int agnss_huada_inject(const agnss_source_t *src, const gps_context_t *ctx);
int agnss_zhongkewei_request(const agnss_source_t *src, const gps_context_t *ctx);
bool gnss_vendor_inject(gnss_type_t type, const uint8_t *data, uint16_t len);
void gnss_vendor_set_type(gnss_type_t type);
bool gnss_vendor_network_rx(uint8_t ch, const uint8_t *data, uint16_t len);

/* Parse one documented Zhongkewei CASBIN/CSIP frame at the beginning of a
 * buffer. Trailing bytes are permitted for a concatenated stream. On success
 * the returned pointer is the complete BA CE frame and the length is its
 * complete wire size, ready for transparent UART forwarding. */
zhongkewei_resp_t zhongkewei_parse_csip_frame(const uint8_t *buf, uint32_t len,
                              const uint8_t **frame, uint16_t *frame_len);

#endif
