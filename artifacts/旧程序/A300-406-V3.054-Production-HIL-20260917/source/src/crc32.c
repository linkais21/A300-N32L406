#include "crc32.h"

uint32_t crc32_update(uint32_t crc, const void *data, uint32_t length)
{
    const uint8_t *p = (const uint8_t *)data;
    while (length--) {
        crc ^= *p++;
        for (uint8_t bit = 0U; bit < 8U; ++bit)
            crc = (crc >> 1) ^ ((crc & 1U) ? 0xEDB88320UL : 0U);
    }
    return crc;
}

uint32_t crc32_compute(const void *data, uint32_t length)
{
    return ~crc32_update(0xFFFFFFFFUL, data, length);
}
