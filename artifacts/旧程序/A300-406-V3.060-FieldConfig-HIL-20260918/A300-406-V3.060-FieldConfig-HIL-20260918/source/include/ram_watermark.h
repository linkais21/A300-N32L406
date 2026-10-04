#ifndef RAM_WATERMARK_H
#define RAM_WATERMARK_H

#include <stdbool.h>
#include <stdint.h>

#define RAM_WATERMARK_PATTERN 0xAAAAAAAAu

typedef struct {
    uint32_t heap_used;
    uint32_t stack_peak;
    uint32_t free_gap;
    uint32_t total_available;
} ram_watermark_t;

bool ram_watermark_measure(const void *region_start, const void *heap_break,
                           const void *stack_top, ram_watermark_t *out);

#endif
