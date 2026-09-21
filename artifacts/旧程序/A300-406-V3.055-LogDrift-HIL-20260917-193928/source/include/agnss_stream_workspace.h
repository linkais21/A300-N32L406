#ifndef AGNSS_STREAM_WORKSPACE_H
#define AGNSS_STREAM_WORKSPACE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define AGNSS_STREAM_WORKSPACE_CAPACITY 4096U

typedef enum {
    AGNSS_STREAM_OWNER_NONE = 0,
    AGNSS_STREAM_OWNER_HUADA
} agnss_stream_owner_t;

/* Main-loop only; acquisition is non-recursive. A vendor retains ownership
 * across chunks until stream completion/reset. Release invalidates pointers.
 * This storage must remain disjoint from service scratch: a partial vendor
 * frame can still be live while the next Flash block overwrites that scratch.
 * See docs/ram03-buffer-contracts.md for bounds and overlap evidence. */
bool agnss_stream_workspace_try_acquire(agnss_stream_owner_t owner);
void agnss_stream_workspace_release(agnss_stream_owner_t owner);
uint8_t *agnss_stream_workspace_buffer(agnss_stream_owner_t owner,
                                       size_t *capacity);

#endif
