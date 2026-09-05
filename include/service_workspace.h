#ifndef SERVICE_WORKSPACE_H
#define SERVICE_WORKSPACE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define SERVICE_WORKSPACE_CAPACITY 512U

typedef enum {
    SERVICE_WORKSPACE_OWNER_NONE = 0,
    SERVICE_WORKSPACE_OWNER_OTA,
    SERVICE_WORKSPACE_OWNER_DIAGNOSTIC
} service_workspace_owner_t;

bool service_workspace_try_acquire(service_workspace_owner_t owner);
void service_workspace_release(service_workspace_owner_t owner);
uint8_t *service_workspace_buffer(size_t *capacity);

#endif
