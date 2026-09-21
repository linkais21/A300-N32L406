"""Compare actual incremental SHA C code with hashlib, including two contexts."""
from pathlib import Path
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
CASES = [(n, chunk) for n in (0, 1, 3, 55, 56, 63, 64, 65, 127, 128,
                            129, 4097, 105808, 155392, 1000000)
         for chunk in (1, 7, 55, 64, 255, 1024)]
HARNESS = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
SHA_DECL
static void print_digest(uint8_t *out) {
    for (unsigned i=0;i<32;i++) printf("%02x",out[i]);
    putchar('\n');
}
int main(void) {
    static const unsigned lengths[]={0,1,3,55,56,63,64,65,127,128,129,4097,105808,155392,1000000};
    static const unsigned chunks[]={1,7,55,64,255,1024};
    uint8_t a[1024],b[1024],out[32];
    for(unsigned l=0;l<sizeof lengths/sizeof *lengths;l++) {
        for(unsigned k=0;k<sizeof chunks/sizeof *chunks;k++) {
            sha256_ctx_t x,y;
            sha256_init(&x);sha256_init(&y);
            sha256_update(&x,NULL,0);sha256_update(&y,NULL,0);
            for(unsigned off=0;off<lengths[l];) {
                unsigned n=lengths[l]-off;
                if(n>chunks[k]) n=chunks[k];
                for(unsigned i=0;i<n;i++) {
                    a[i]=(uint8_t)((off+i)*37U+11U);
                    b[i]=(uint8_t)((off+i)*19U+83U);
                }
                sha256_update(&x,a,n);sha256_update(&y,b,n);
                sha256_update(&x,NULL,0);
                off+=n;
            }
            sha256_final(&y,out);print_digest(out);
            sha256_final(&x,out);print_digest(out);
        }
    }
    sha256_ctx_t known;
    sha256_init(&known);sha256_update(&known,(const uint8_t *)"abc",3);
    sha256_final(&known,out);print_digest(out);
    return 0;
}
'''


def run(legacy_source=None):
    cc = os.environ.get("CC") or shutil.which("gcc") or shutil.which("cc")
    assert cc, "host C compiler required"
    if legacy_source:
        source = Path(legacy_source).read_text(encoding="utf-8")
        core = source[source.index("typedef struct { uint32_t h[8]; uint64_t bits;"):
                      source.index("static bool parse_url")]
        decl = core.replace("fota_sha256_t", "sha256_ctx_t").replace("fota_sha_", "sha256_")
        extra = []
    else:
        assert (ROOT / "src/sha256.c").exists(), "App shared SHA core not implemented"
        decl = '#include "sha256.h"'
        extra = [str(ROOT / "src/sha256.c")]
    expected = []
    for n, _ in CASES:
        for mul, add in ((19, 83), (37, 11)):
            expected.append(hashlib.sha256(bytes((i*mul+add)&255 for i in range(n))).hexdigest())
    expected.append(hashlib.sha256(b"abc").hexdigest())
    with tempfile.TemporaryDirectory(prefix="a300_sha_vectors_") as td:
        p = Path(td)
        (p / "test.c").write_text(HARNESS.replace("SHA_DECL", decl), encoding="utf-8")
        cmd = [cc, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror",
               "-I", str(ROOT / "include"), str(p / "test.c"), *extra,
               "-o", str(p / "test.exe")]
        built = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        assert built.returncode == 0, built.stderr
        result = subprocess.run([str(p / "test.exe")], capture_output=True,
                                text=True, timeout=30)
        assert result.returncode == 0, result.stderr
        actual = result.stdout.splitlines()
        assert len(actual) == len(expected)
        for i, (a, e) in enumerate(zip(actual, expected)):
            assert a == e, f"digest {i}: {a} != {e}"
    print(f"{'legacy' if legacy_source else 'shared'} SHA: {len(expected)} digests PASS")


if __name__ == "__main__":
    run(sys.argv[2] if len(sys.argv) == 3 and sys.argv[1] == "--legacy-source" else None)
