#include "ram_watermark.h"

#include <stddef.h>
#include <stdint.h>

bool ram_watermark_measure(const void *region_start, const void *heap_break,
                           const void *stack_top, ram_watermark_t *out)
{
    uintptr_t start = (uintptr_t)region_start;
    uintptr_t heap = (uintptr_t)heap_break;
    uintptr_t top = (uintptr_t)stack_top;
    uintptr_t scan;

    if (out == NULL || start > heap || heap > top ||
        (start & (sizeof(uint32_t) - 1U)) != 0U ||
        (top & (sizeof(uint32_t) - 1U)) != 0U)
        return false;

    scan = (heap + sizeof(uint32_t) - 1U) & ~(uintptr_t)(sizeof(uint32_t) - 1U);
    if (scan > top) return false;
    while (scan < top && *(const uint32_t *)scan == RAM_WATERMARK_PATTERN)
        scan += sizeof(uint32_t);

    out->heap_used = (uint32_t)(heap - start);
    out->stack_peak = (uint32_t)(top - scan);
    out->free_gap = (uint32_t)(scan - heap);
    out->total_available = (uint32_t)(top - start);
    return true;
}
