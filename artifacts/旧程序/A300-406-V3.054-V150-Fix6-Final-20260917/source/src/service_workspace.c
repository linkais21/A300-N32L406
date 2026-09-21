#include "service_workspace.h"

/* Parameter transactions also use this storage for device_config_t. */
static union {
    uint32_t alignment;
    uint8_t bytes[SERVICE_WORKSPACE_CAPACITY];
} s_service_workspace;
static uint8_t s_owner = SERVICE_WORKSPACE_OWNER_NONE;

bool service_workspace_try_acquire(service_workspace_owner_t owner)
{
    if (owner == SERVICE_WORKSPACE_OWNER_NONE || s_owner != SERVICE_WORKSPACE_OWNER_NONE)
        return false;
    s_owner = owner;
    return true;
}

void service_workspace_release(service_workspace_owner_t owner)
{
    if (owner != SERVICE_WORKSPACE_OWNER_NONE && s_owner == owner)
        s_owner = SERVICE_WORKSPACE_OWNER_NONE;
}

uint8_t *service_workspace_buffer(size_t *capacity)
{
    if (capacity != NULL)
        *capacity = SERVICE_WORKSPACE_CAPACITY;
    return s_service_workspace.bytes;
}
