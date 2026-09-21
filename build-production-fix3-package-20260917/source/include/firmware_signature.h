#ifndef A300_FIRMWARE_SIGNATURE_H
#define A300_FIRMWARE_SIGNATURE_H

#include <stdbool.h>
#include <stdint.h>

bool firmware_signature_verify(const uint8_t digest[32],
                               const uint8_t signature[64]);

#endif
