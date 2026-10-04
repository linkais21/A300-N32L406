#include "agnss_stream_workspace.h"

static uint8_t s_workspace[AGNSS_STREAM_WORKSPACE_CAPACITY];
static agnss_stream_owner_t s_owner = AGNSS_STREAM_OWNER_NONE;

bool agnss_stream_workspace_try_acquire(agnss_stream_owner_t owner)
{
    if (owner == AGNSS_STREAM_OWNER_NONE ||
        s_owner != AGNSS_STREAM_OWNER_NONE)
        return false;
    s_owner = owner;
    return true;
}

void agnss_stream_workspace_release(agnss_stream_owner_t owner)
{
    if (owner != AGNSS_STREAM_OWNER_NONE && s_owner == owner)
        s_owner = AGNSS_STREAM_OWNER_NONE;
}

uint8_t *agnss_stream_workspace_buffer(agnss_stream_owner_t owner,
                                       size_t *capacity)
{
    if (owner == AGNSS_STREAM_OWNER_NONE || s_owner != owner)
        return NULL;
    if (capacity != NULL)
        *capacity = AGNSS_STREAM_WORKSPACE_CAPACITY;
    return s_workspace;
}
