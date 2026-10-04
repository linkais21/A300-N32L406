#ifndef PLATE_ENCODING_H
#define PLATE_ENCODING_H
#include <stdint.h>
/* Three UTF-8 bytes for province codes 1..39; unsupported codes return NULL. */
const uint8_t *plate_province_utf8(uint8_t code);
/* Accept stored UTF-8 prefixes and legacy GBK; output is not NUL terminated. */
uint8_t plate_encode_gbk(const char *plate, uint8_t *out, uint8_t capacity);
#endif
