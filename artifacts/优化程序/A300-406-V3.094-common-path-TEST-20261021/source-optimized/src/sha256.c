#include "sha256.h"
#include <string.h>

static uint32_t rotr(uint32_t x, uint8_t n)
{
    return (x >> n) | (x << (32U - n));
}

static void sha256_block(sha256_ctx_t *ctx, const uint8_t *p)
{
    static const uint32_t k[64] = {
        0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
        0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
        0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
        0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
        0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
        0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
        0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
        0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2
    };
    uint32_t w[16], a, b, c, d, e, f, g, h;
    a=ctx->h[0]; b=ctx->h[1]; c=ctx->h[2]; d=ctx->h[3];
    e=ctx->h[4]; f=ctx->h[5]; g=ctx->h[6]; h=ctx->h[7];
    for (unsigned i = 0; i < 64; ++i) {
        /* Only the previous 16 schedule words are live. Read all inputs
         * before replacing W[i-16] in its circular slot. */
        unsigned slot = i & 15U;
        uint32_t word;
        if (i < 16U) {
            word = ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
                      ((uint32_t)p[2] << 8) | p[3];
            p += 4;
        } else {
            uint32_t x = w[(i-15U) & 15U];
            uint32_t y = w[(i-2U) & 15U];
            uint32_t q = rotr(x,7) ^ rotr(x,18) ^ (x >> 3);
            uint32_t r = rotr(y,17) ^ rotr(y,19) ^ (y >> 10);
            word = w[slot] + q + w[(i-7U) & 15U] + r;
        }
        w[slot] = word;
        uint32_t s1 = rotr(e,6) ^ rotr(e,11) ^ rotr(e,25);
        uint32_t ch = (e & f) ^ (~e & g);
        uint32_t s0 = rotr(a,2) ^ rotr(a,13) ^ rotr(a,22);
        uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
        uint32_t t1 = h + s1 + ch + k[i] + word;
        uint32_t t2 = s0 + maj;
        h=g; g=f; f=e; e=d+t1; d=c; c=b; b=a; a=t1+t2;
    }
    ctx->h[0]+=a; ctx->h[1]+=b; ctx->h[2]+=c; ctx->h[3]+=d;
    ctx->h[4]+=e; ctx->h[5]+=f; ctx->h[6]+=g; ctx->h[7]+=h;
}

void sha256_init(sha256_ctx_t *ctx)
{
    static const uint32_t initial[8] = {
        0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,
        0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19
    };
    memcpy(ctx->h, initial, sizeof initial);
    ctx->bits = 0;
    ctx->used = 0;
}

void sha256_update(sha256_ctx_t *ctx, const uint8_t *data, uint32_t length)
{
    ctx->bits += (uint64_t)length * 8U;
    while (length) {
        uint32_t room = 64U - ctx->used;
        uint32_t n = length < room ? length : room;
        memcpy(ctx->block + ctx->used, data, n);
        ctx->used += (uint8_t)n;
        data += n;
        length -= n;
        if (ctx->used == 64U) {
            sha256_block(ctx, ctx->block);
            ctx->used = 0;
        }
    }
}

void sha256_final(sha256_ctx_t *ctx, uint8_t output[32])
{
    ctx->block[ctx->used++] = 0x80;
    while (ctx->used != 56U) {
        if (ctx->used == 64U) {
            sha256_block(ctx, ctx->block);
            ctx->used = 0;
        }
        ctx->block[ctx->used++] = 0;
    }
    uint64_t bits = ctx->bits;
    for (unsigned i = 64; i > 56; --i) {
        ctx->block[i-1] = (uint8_t)bits;
        bits >>= 8;
    }
    sha256_block(ctx, ctx->block);
    for (unsigned i = 0; i < 8; ++i) {
        output[4*i] = (uint8_t)(ctx->h[i] >> 24);
        output[4*i+1] = (uint8_t)(ctx->h[i] >> 16);
        output[4*i+2] = (uint8_t)(ctx->h[i] >> 8);
        output[4*i+3] = (uint8_t)ctx->h[i];
    }
}
