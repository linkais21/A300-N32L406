#ifndef A300_SHA256_H
#define A300_SHA256_H

#include <stdint.h>

/* Caller-owned, non-persistent context. Independent callers must use separate
 * contexts. No heap, global workspace, Flash access or hardware dependencies. */
typedef struct {
    uint32_t h[8];
    uint64_t bits;
    uint8_t block[64];
    uint8_t used;
} sha256_ctx_t;

void sha256_init(sha256_ctx_t *ctx);
/* data may be NULL only when length is zero. */
void sha256_update(sha256_ctx_t *ctx, const uint8_t *data, uint32_t length);
/* Consumes the context. Reinitialize before reuse; output must not alias ctx. */
void sha256_final(sha256_ctx_t *ctx, uint8_t output[32]);

#endif
