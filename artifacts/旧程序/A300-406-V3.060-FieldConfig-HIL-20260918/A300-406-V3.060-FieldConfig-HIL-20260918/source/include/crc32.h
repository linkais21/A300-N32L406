#ifndef CRC32_H
#define CRC32_H

#include <stdint.h>

/* CRC-32 (IEEE 802.3 / zlib polynomial, reflected 0xEDB88320), bit-serial. */

/* Feed one chunk into a running, non-inverted CRC accumulator. Start with
 * crc = 0xFFFFFFFFUL and invert the final result for the standard CRC-32
 * value, or keep chaining the returned value across successive calls for
 * streaming input read in pieces. */
uint32_t crc32_update(uint32_t crc, const void *data, uint32_t length);

/* One-shot CRC-32 over a single contiguous buffer. */
uint32_t crc32_compute(const void *data, uint32_t length);

#endif
