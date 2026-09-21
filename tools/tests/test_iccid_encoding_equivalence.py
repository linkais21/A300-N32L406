"""Exercise real terminal-info encoding for every nibble/position and rejection."""
import argparse
from pathlib import Path
import subprocess
import tempfile

from test_jt808_dual_session import compiler

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'src/jt808_terminal_info.c')
    args = parser.parse_args()
    cc = compiler()
    assert cc, 'Host C compiler required'
    harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include "jt808_terminal_info.h"
static char input[22];
bool terminal_identity_load(char out[8]) { memcpy(out, "1234567", 8); return true; }
void ec800m_get_iccid(char *out, uint8_t size) {
    assert(size >= sizeof input); memcpy(out, input, sizeof input);
}
int main(void) {
    const char alphabet[] = "0123456789ABCDEFabcdef";
    uint8_t output[85], expected[10];
    uint16_t length;
    for (unsigned n = 19; n <= 20; ++n) {
        for (unsigned pos = 0; pos < n; ++pos) {
            for (unsigned digit = 0; digit < sizeof alphabet - 1; ++digit) {
                memset(input, '0', n); input[n] = 0;
                input[pos] = alphabet[digit];
                memset(expected, 0, sizeof expected);
                unsigned nibble = digit < 16 ? digit : digit - 6;
                unsigned padded_pos = pos + (20 - n);
                expected[padded_pos / 2] = (uint8_t)(nibble << (padded_pos % 2 ? 0 : 4));
                memset(output, 0xa5, sizeof output);
                assert(jt808_terminal_info_encode(output, 83, &length) == JT808_TERMINAL_INFO_OK);
                assert(length == 83 && output[83] == 0xa5 && output[84] == 0xa5);
                assert(memcmp(output + 34, expected, 10) == 0);
            }
            for (unsigned byte = 1; byte <= 255; ++byte) {
                if (strchr(alphabet, (int)byte)) continue;
                memset(input, '0', n); input[n] = 0; input[pos] = (char)byte;
                assert(jt808_terminal_info_encode(output, 83, &length) == JT808_TERMINAL_INFO_INVALID_ICCID);
                assert(length == 0);
            }
        }
    }
    for (unsigned n = 0; n <= 21; ++n) {
        if (n == 19 || n == 20) continue;
        memset(input, '0', n); input[n] = 0;
        assert(jt808_terminal_info_encode(output, 83, &length) == JT808_TERMINAL_INFO_INVALID_ICCID);
        assert(length == 0);
    }
    memset(input, '0', 20); input[20] = 0;
    for (unsigned capacity = 0; capacity < 83; ++capacity) {
        memset(output, 0xa5, sizeof output);
        assert(jt808_terminal_info_encode(output, capacity, &length) == JT808_TERMINAL_INFO_NO_SPACE);
        assert(length == 0 && output[0] == 0xa5);
    }
    assert(jt808_terminal_info_encode(NULL, 83, &length) == JT808_TERMINAL_INFO_INVALID_ARGUMENT);
    assert(jt808_terminal_info_encode(output, 83, NULL) == JT808_TERMINAL_INFO_INVALID_ARGUMENT);
    return 0;
}
'''
    with tempfile.TemporaryDirectory(prefix='iccid_equivalence_') as directory:
        temp = Path(directory)
        source, binary = temp / 'h.c', temp / 'h.exe'
        source.write_text(harness, encoding='ascii')
        (temp / 'n32l40x.h').write_text('#pragma once\n', encoding='ascii')
        subprocess.run([cc, '-std=c99', '-Wall', '-Wextra', '-Werror',
                        '-I', str(temp), '-I', str(ROOT / 'include'), str(source), str(args.source.resolve()),
                        '-o', str(binary)], check=True, timeout=60)
        subprocess.run([str(binary)], check=True, timeout=30)
    print('test_iccid_encoding_equivalence: PASS')


if __name__ == '__main__':
    main()
