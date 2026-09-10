#ifndef AGNSS_STREAM_WORKSPACE_H
#define AGNSS_STREAM_WORKSPACE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define AGNSS_STREAM_WORKSPACE_CAPACITY 4096U

typedef enum {
    AGNSS_STREAM_OWNER_NONE = 0,
    AGNSS_STREAM_OWNER_HUADA,
    AGNSS_STREAM_OWNER_ZHONGKEWEI
} agnss_stream_owner_t;

bool agnss_stream_workspace_try_acquire(agnss_stream_owner_t owner);
void agnss_stream_workspace_release(agnss_stream_owner_t owner);
uint8_t *agnss_stream_workspace_buffer(agnss_stream_owner_t owner,
                                       size_t *capacity);

#endif
