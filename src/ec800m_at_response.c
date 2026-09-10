#include "ec800m_at_response.h"

#include <stddef.h>
#include <string.h>

static bool bytes_equal(const uint8_t *data, const char *value, uint16_t length)
{
    return memcmp(data, value, length) == 0;
}

bool ec800m_at_response_has_line(const char *data, uint16_t length,
                                 const char *value)
{
    size_t value_length;
    uint16_t pos;

    if (data == NULL || value == NULL) return false;
    value_length = strlen(value);
    if (value_length == 0U || value_length + 2U > length)
        return false;

    for (pos = 0U; (size_t)pos + value_length + 2U <= length; ++pos) {
        bool line_start = pos == 0U ||
                          (pos >= 2U && data[pos - 2U] == '\r' &&
                           data[pos - 1U] == '\n');
        if (line_start && memcmp(&data[pos], value, value_length) == 0 &&
            data[pos + value_length] == '\r' &&
            data[pos + value_length + 1U] == '\n')
            return true;
    }
    return false;
}

bool ec800m_at_response_has_line_prefix(const char *data, uint16_t length,
                                        const char *prefix)
{
    size_t prefix_length;
    uint16_t pos;

    if (data == NULL || prefix == NULL) return false;
    prefix_length = strlen(prefix);
    if (prefix_length == 0U || prefix_length + 2U > length) return false;
    for (pos = 0U; (size_t)pos + prefix_length + 2U <= length; ++pos) {
        uint16_t end;
        bool line_start = pos == 0U ||
                          (pos >= 2U && data[pos - 2U] == '\r' &&
                           data[pos - 1U] == '\n');
        if (!line_start || memcmp(&data[pos], prefix, prefix_length) != 0)
            continue;
        for (end = (uint16_t)(pos + prefix_length); end + 1U < length;
             ++end) {
            if (data[end] == '\r' && data[end + 1U] == '\n') return true;
        }
    }
    return false;
}

ec800m_at_end_t ec800m_at_response_end(const char *data, uint16_t length)
{
    if (ec800m_at_response_has_line(data, length, "ERROR"))
        return EC800M_AT_ERROR;
    if (ec800m_at_response_has_line(data, length, "OK"))
        return EC800M_AT_OK;
    return EC800M_AT_PENDING;
}

bool ec800m_parse_reg_status(const char *data, const char *prefix, int *status)
{
    const char *line;
    const char *cursor;
    size_t prefix_length;
    unsigned int mode = 0U;
    unsigned int registration = 0U;

    if (data == NULL || prefix == NULL || status == NULL ||
        ec800m_at_response_end(data, (uint16_t)strlen(data)) != EC800M_AT_OK)
        return false;

    prefix_length = strlen(prefix);
    line = strstr(data, prefix);
    if (line == NULL)
        return false;

    cursor = line + prefix_length;
    while (*cursor == ' ' || *cursor == '\t')
        ++cursor;
    if (*cursor < '0' || *cursor > '9')
        return false;
    do {
        mode = mode * 10U + (unsigned int)(*cursor - '0');
        ++cursor;
    } while (*cursor >= '0' && *cursor <= '9');
    (void)mode;

    if (*cursor++ != ',')
        return false;
    while (*cursor == ' ' || *cursor == '\t')
        ++cursor;
    if (*cursor < '0' || *cursor > '9')
        return false;
    do {
        registration = registration * 10U + (unsigned int)(*cursor - '0');
        ++cursor;
    } while (*cursor >= '0' && *cursor <= '9');

    if (registration > 5U || cursor[0] != '\r' || cursor[1] != '\n')
        return false;

    *status = (int)registration;
    return true;
}

bool ec800m_parse_qird_response_diag(const uint8_t *data, uint16_t length,
                                     const uint8_t **payload,
                                     uint16_t *payload_length,
                                     ec800m_qird_diag_t *diag)
{
    static const char prefix[] = "+QIRD: ";
    static const char tail[] = "\r\nOK\r\n";
    static const char tail_with_blank_line[] = "\r\n\r\nOK\r\n";
    uint16_t pos;
    uint32_t declared = 0U;
    uint16_t start;
    uint16_t remaining;
    uint8_t tail_mask = 0U;
    uint8_t i;

    if (diag != NULL) {
        memset(diag, 0, sizeof(*diag));
        diag->stage = EC800M_QIRD_STAGE_ARGUMENT;
        diag->total_length = length;
        diag->header_offset = -1;
    }

    if (data == NULL || payload == NULL || payload_length == NULL)
        return false;
    for (pos = 0U; pos + sizeof(prefix) - 1U <= length; ++pos) {
        if ((pos == 0U ||
             (pos >= 2U && data[pos - 2U] == '\r' && data[pos - 1U] == '\n')) &&
            bytes_equal(&data[pos], prefix, sizeof(prefix) - 1U))
            break;
    }
    if (pos + sizeof(prefix) - 1U > length) {
        if (diag != NULL) diag->stage = EC800M_QIRD_STAGE_HEADER;
        return false;
    }
    if (diag != NULL) diag->header_offset = (int16_t)pos;
    pos = (uint16_t)(pos + sizeof(prefix) - 1U);
    if (pos >= length || data[pos] < '0' || data[pos] > '9') {
        if (diag != NULL) diag->stage = EC800M_QIRD_STAGE_LENGTH;
        return false;
    }
    do {
        declared = declared * 10U + (uint32_t)(data[pos] - '0');
        if (declared > UINT16_MAX) {
            if (diag != NULL) diag->stage = EC800M_QIRD_STAGE_LENGTH;
            return false;
        }
        ++pos;
    } while (pos < length && data[pos] >= '0' && data[pos] <= '9');
    if (diag != NULL) diag->declared_length = (uint16_t)declared;
    if (pos + 2U > length || data[pos] != '\r' || data[pos + 1U] != '\n') {
        if (diag != NULL) diag->stage = EC800M_QIRD_STAGE_HEADER_END;
        return false;
    }
    start = (uint16_t)(pos + 2U);
    if (declared > (uint32_t)(length - start)) {
        if (diag != NULL) {
            diag->stage = EC800M_QIRD_STAGE_PAYLOAD;
            diag->remaining_length = (uint16_t)(length - start);
        }
        return false;
    }
    pos = (uint16_t)(start + declared);
    remaining = (uint16_t)(length - pos);
    for (i = 0U; i < sizeof(tail) - 1U && i < remaining; ++i) {
        if (data[pos + i] == (uint8_t)tail[i])
            tail_mask = (uint8_t)(tail_mask | (uint8_t)(1U << i));
    }
    if (diag != NULL) {
        diag->remaining_length = remaining;
        diag->tail_mask = tail_mask;
    }
    if (!((remaining >= sizeof(tail) - 1U &&
           bytes_equal(&data[pos], tail, sizeof(tail) - 1U)) ||
          (remaining >= sizeof(tail_with_blank_line) - 1U &&
           bytes_equal(&data[pos], tail_with_blank_line,
                       sizeof(tail_with_blank_line) - 1U)))) {
        if (diag != NULL) diag->stage = EC800M_QIRD_STAGE_TAIL;
        return false;
    }
    *payload = &data[start];
    *payload_length = (uint16_t)declared;
    if (diag != NULL) diag->stage = EC800M_QIRD_STAGE_OK;
    return true;
}

bool ec800m_parse_qird_response(const uint8_t *data, uint16_t length,
                                const uint8_t **payload,
                                uint16_t *payload_length)
{
    return ec800m_parse_qird_response_diag(data, length, payload,
                                           payload_length, NULL);
}
