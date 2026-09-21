#ifndef SERVICE_WORKSPACE_H
#define SERVICE_WORKSPACE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define SERVICE_WORKSPACE_CAPACITY 1024U

typedef enum {
    SERVICE_WORKSPACE_OWNER_NONE = 0,
    SERVICE_WORKSPACE_OWNER_OTA,
    SERVICE_WORKSPACE_OWNER_DIAGNOSTIC,
    SERVICE_WORKSPACE_OWNER_AGNSS,
    SERVICE_WORKSPACE_OWNER_PARAMS
} service_workspace_owner_t;

/* Main-loop only, non-recursive ownership; not an ISR lock. The unguarded
 * buffer accessor does not acquire ownership or extend the data lifetime.
 * Consume data before another owner can reuse it; never retain a pointer
 * across an asynchronous handoff without retaining ownership.
 * See docs/ram03-buffer-contracts.md for the synchronous AGNSS handoff. */
bool service_workspace_try_acquire(service_workspace_owner_t owner);
void service_workspace_release(service_workspace_owner_t owner);
uint8_t *service_workspace_buffer(size_t *capacity);

#endif
