#include "jt808_terminal_info.h"

#include "config.h"
#include "ec800m.h"
#include "terminal_identity.h"

#include <stddef.h>
#include <string.h>

static uint8_t iccid_nibble(char value)
{
    if (value >= '0' && value <= '9') return (uint8_t)(value - '0');
    if (value >= 'A' && value <= 'F') return (uint8_t)(value - 'A' + 10);
    if (value >= 'a' && value <= 'f') return (uint8_t)(value - 'a' + 10);
    return 0xFFU;
}

static bool iccid_valid(const char *iccid, size_t *length)
{
    size_t count = 0U;
    if (iccid == NULL || length == NULL) return false;
    while (count < 20U && iccid_nibble(iccid[count]) <= 0x0FU)
        ++count;
    if (iccid[count] != '\0' || (count != 19U && count != 20U)) return false;
    *length = count;
    return true;
}

static void encode_iccid(const char *iccid, size_t length, uint8_t out[10])
{
    uint8_t digits[20];
    size_t source = 0U;
    size_t target = 0U;
    if (length == 19U) digits[target++] = 0U;
    while (source < length) digits[target++] = iccid_nibble(iccid[source++]);
    for (target = 0U; target < 10U; ++target)
        out[target] = (uint8_t)((digits[target * 2U] << 4) |
                               digits[target * 2U + 1U]);
}

jt808_terminal_info_result_t jt808_terminal_info_encode(
    uint8_t *body, uint16_t capacity, uint16_t *length)
{
    char terminal_id[8];
    char iccid[22];
    size_t iccid_length;
    size_t firmware_length = strlen(FW_VERSION_STR);
    uint16_t position = 0U;

    if (body == NULL || length == NULL)
        return JT808_TERMINAL_INFO_INVALID_ARGUMENT;
    *length = 0U;
    if (capacity < JT808_TERMINAL_INFO_BODY_LENGTH)
        return JT808_TERMINAL_INFO_NO_SPACE;
    if (!terminal_identity_load(terminal_id))
        return JT808_TERMINAL_INFO_INVALID_IDENTITY;
    memset(iccid, 0, sizeof(iccid));
    ec800m_get_iccid(iccid, sizeof(iccid));
    if (!iccid_valid(iccid, &iccid_length))
        return JT808_TERMINAL_INFO_INVALID_ICCID;
    if (firmware_length > 255U)
        return JT808_TERMINAL_INFO_INVALID_ARGUMENT;

    body[position++] = 0x00U;
    body[position++] = 0x0DU;
    memcpy(body + position, FW_MANUFACTURER_ID_STR, 5U);
    position += 5U;
    memset(body + position, 0, 20U);
    memcpy(body + position, FW_JT808_MODEL_STR, strlen(FW_JT808_MODEL_STR));
    position += 20U;
    memcpy(body + position, terminal_id, 7U);
    position += 7U;
    encode_iccid(iccid, iccid_length, body + position);
    position += 10U;
    body[position++] = 0U;
    body[position++] = (uint8_t)firmware_length;
    memcpy(body + position, FW_VERSION_STR, firmware_length);
    position += (uint16_t)firmware_length;
    body[position++] = 0x02U;
    body[position++] = 0x20U;

    *length = position;
    return position == JT808_TERMINAL_INFO_BODY_LENGTH ?
           JT808_TERMINAL_INFO_OK : JT808_TERMINAL_INFO_INVALID_ARGUMENT;
}
