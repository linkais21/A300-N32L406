#ifndef EC800M_AT_RESPONSE_H
#define EC800M_AT_RESPONSE_H

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    EC800M_AT_PENDING = 0,
    EC800M_AT_OK,
    EC800M_AT_ERROR,
} ec800m_at_end_t;

typedef enum {
    EC800M_QIRD_STAGE_OK = 0,
    EC800M_QIRD_STAGE_ARGUMENT,
    EC800M_QIRD_STAGE_HEADER,
    EC800M_QIRD_STAGE_LENGTH,
    EC800M_QIRD_STAGE_HEADER_END,
    EC800M_QIRD_STAGE_PAYLOAD,
    EC800M_QIRD_STAGE_TAIL,
} ec800m_qird_stage_t;

typedef struct {
    ec800m_qird_stage_t stage;
    uint16_t total_length;
    int16_t header_offset;
    uint16_t declared_length;
    uint16_t remaining_length;
    uint8_t tail_mask;
} ec800m_qird_diag_t;

ec800m_at_end_t ec800m_at_response_end(const char *data, uint16_t length);
bool ec800m_parse_reg_status(const char *data, const char *prefix, int *status);
bool ec800m_parse_qird_response(const uint8_t *data, uint16_t length,
                                const uint8_t **payload,
                                uint16_t *payload_length);
bool ec800m_parse_qird_response_diag(const uint8_t *data, uint16_t length,
                                     const uint8_t **payload,
                                     uint16_t *payload_length,
                                     ec800m_qird_diag_t *diag);

#endif
