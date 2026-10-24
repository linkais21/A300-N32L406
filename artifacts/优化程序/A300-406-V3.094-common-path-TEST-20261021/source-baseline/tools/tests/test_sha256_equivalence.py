"""Compare real streaming SHA-256 with hashlib across padding/block boundaries."""
from pathlib import Path
import argparse
import hashlib
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'src/sha256.c')
    args = parser.parse_args()
    data = bytes((i * 73 + (i >> 3) * 19) & 255 for i in range(106496))
    lengths = sorted(set(range(130)) | {255, 256, 257, 4095, 4096, 4097, len(data)})
    cases = ',\n'.join('{' + str(n) + ',{' + ','.join(
        str(b) for b in hashlib.sha256(data[:n]).digest()) + '}}' for n in lengths)
    source = r'''
#include <assert.h>
#include <stddef.h>
#include <string.h>
#include "sha256.h"
static const struct { uint32_t length; uint8_t digest[32]; } cases[] = { CASES };
static uint8_t data[106496];
int main(void) {
    const uint32_t chunks[] = {1, 7, 55, 56, 63, 64, 65, 256, 4096, sizeof data};
    sha256_ctx_t ctx, other;
    uint8_t digest[32], second[32];
    for (uint32_t i = 0; i < sizeof data; ++i)
        data[i] = (uint8_t)(i * 73U + (i >> 3) * 19U);
    for (unsigned c = 0; c < sizeof cases / sizeof cases[0]; ++c) {
        for (unsigned k = 0; k < sizeof chunks / sizeof chunks[0]; ++k) {
            sha256_init(&ctx);
            sha256_init(&other);
            sha256_update(&ctx, NULL, 0);
            for (uint32_t pos = 0; pos < cases[c].length;) {
                uint32_t n = cases[c].length - pos;
                if (n > chunks[k]) n = chunks[k];
                sha256_update(&ctx, data + pos, n);
                /* Interleave independent contexts to catch shared scratch. */
                sha256_update(&other, data + pos, n);
                sha256_update(&ctx, NULL, 0);
                pos += n;
            }
            sha256_final(&ctx, digest);
            sha256_final(&other, second);
            assert(memcmp(digest, cases[c].digest, 32) == 0);
            assert(memcmp(second, digest, 32) == 0);
        }
    }
    /* Widely published multi-block known-answer vector. */
    static const uint8_t million_a_digest[32] = {
        0xcd,0xc7,0x6e,0x5c,0x99,0x14,0xfb,0x92,0x81,0xa1,0xc7,0xe2,0x84,0xd7,0x3e,0x67,
        0xf1,0x80,0x9a,0x48,0xa4,0x97,0x20,0x0e,0x04,0x6d,0x39,0xcc,0xc7,0x11,0x2c,0xd0
    };
    memset(data, 'a', 1000);
    sha256_init(&ctx);
    for (unsigned i = 0; i < 1000; ++i) sha256_update(&ctx, data, 1000);
    sha256_final(&ctx, digest);
    assert(memcmp(digest, million_a_digest, 32) == 0);
    /* Exercise all length bytes without hashing exabytes. final() retains
     * the last padded block; these synthetic counters test serialization. */
    const uint64_t bit_counts[] = {0, 8, UINT64_C(0xfffffff8),
        UINT64_C(0x100000000), UINT64_C(0x0123456789abcde8), UINT64_MAX - 7U};
    for (unsigned i = 0; i < sizeof bit_counts / sizeof bit_counts[0]; ++i) {
        sha256_init(&ctx);
        ctx.bits = bit_counts[i];
        sha256_final(&ctx, digest);
        assert(ctx.bits == bit_counts[i]);
        for (unsigned j = 0; j < 8; ++j)
            assert(ctx.block[56+j] == (uint8_t)(bit_counts[i] >> (56-8*j)));
    }
    return 0;
}
'''.replace('CASES', cases)
    cc = shutil.which('gcc') or shutil.which('clang')
    assert cc, 'Host C compiler required'
    with tempfile.TemporaryDirectory(prefix='sha256_equivalence_') as directory:
        temp = Path(directory)
        harness, exe = temp / 'test.c', temp / 'test.exe'
        harness.write_text(source, encoding='ascii')
        subprocess.run([cc, '-std=c99', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-I', str(ROOT / 'include'), str(harness), str(args.source.resolve()),
                        '-o', str(exe)], check=True, timeout=60)
        subprocess.run([str(exe)], check=True, timeout=30)
    print(f'SHA-256 hashlib/streaming/context equivalence: PASS ({len(lengths)} lengths, 10 chunk sizes)')


if __name__ == '__main__':
    main()
