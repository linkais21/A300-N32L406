"""Compare actual filter math with the original mean and pairwise span oracle."""
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
HARNESS = r'''
#define main filter_suite_main
#include "tools/tests/gps_report_filter_host.c"
#undef main
#include "src/gps_report_filter.c"

static uint32_t random_state = 12345;
static uint32_t next_random(void) {
    random_state = random_state * 1664525u + 1013904223u;
    return random_state;
}
static double original_mean(const int32_t *values, bool longitude) {
    double origin = (double)values[0] / 10000000.0;
    double sum = origin, low = origin, high = origin;
    for (unsigned i = 1; i < 5; ++i) {
        double value = (double)values[i] / 10000000.0;
        if (longitude) {
            if (value-origin > 180.0) value -= 360.0;
            else if (value-origin < -180.0) value += 360.0;
        }
        sum += value;
        if (value < low) low = value;
        if (value > high) high = value;
    }
    double mean = (sum-low-high)/3.0;
    if (longitude) {
        if (mean > 180.0) mean -= 360.0;
        else if (mean < -180.0) mean += 360.0;
    }
    return mean;
}
int main(void) {
    for (unsigned trial = 0; trial < 20000; ++trial) {
        int32_t values[5];
        bool longitude = trial % 2u;
        for (unsigned i = 0; i < 5; ++i) {
            values[i] = (int32_t)(next_random() % 1800000001u);
            if (next_random() & 0x100u) values[i] = -values[i];
            if (!longitude) values[i] /= 2;
        }
        if (trial < 20) {
            for (unsigned i = 0; i < 5; ++i)
                values[i] = (i & 1u) ? 1800000000 : -1800000000;
            longitude = true;
        }
        /* Original binary64 mean in degrees; output is now rounded 1e-7 deg,
         * so the circular error must be at most half an e7 unit. */
        double expected = original_mean(values, longitude);
        int32_t actual = trimmed_mean(values);
        double error = fabs((double)actual / 10000000.0 - expected);
        if (longitude && error > 180.0) error = fabs(error - 360.0);
        assert(error <= 0.5e-7 + 1e-12);
        assert(llabs((long long)actual) <= (longitude ? 1800000000LL : 900000000LL));
        /* Exact integer oracle: nearest e7 of the trimmed mean, ties of thirds
         * cannot occur, sign-symmetric for southern/western hemispheres. */
        {
            int64_t origin = values[0], sum = origin, low = origin, high = origin;
            for (unsigned i = 1; i < 5; ++i) {
                int64_t v = values[i];
                if (longitude) {
                    if (v - origin > 1800000000LL) v -= 3600000000LL;
                    else if (v - origin < -1800000000LL) v += 3600000000LL;
                }
                sum += v; if (v < low) low = v; if (v > high) high = v;
            }
            sum -= low + high;
            int64_t q = sum / 3, r = sum % 3;
            if (r == 2) ++q; else if (r == -2) --q;
            if (longitude) {
                if (q > 1800000000LL) q -= 3600000000LL;
                else if (q < -1800000000LL) q += 3600000000LL;
            }
            if (actual != (int32_t)q)
                printf("trimmed_mean mismatch trial=%u lon=%d v=%ld,%ld,%ld,%ld,%ld exp=%lld act=%ld\n",
                       trial, (int)longitude, (long)values[0], (long)values[1], (long)values[2],
                       (long)values[3], (long)values[4], (long long)q, (long)actual);
            assert(actual == (int32_t)q);
        }
        s_report.accel_count = (uint8_t)(1 + trial % 5);
        for (unsigned i = 0; i < s_report.accel_count; ++i)
            for (unsigned axis = 0; axis < 3; ++axis)
                s_report.acceleration[i][axis] = (int16_t)(next_random() % 4096u) - 2048;
        uint32_t expected_span = 0;
        for (unsigned i = 0; i < s_report.accel_count; ++i)
            for (unsigned j = 0; j < s_report.accel_count; ++j)
                for (unsigned axis = 0; axis < 3; ++axis) {
                    int delta = s_report.acceleration[i][axis] - s_report.acceleration[j][axis];
                    if (delta > (int)expected_span) expected_span = (uint32_t)delta;
                }
        assert(acceleration_span() == expected_span);
    }
    puts("PASS: 20000 mean/span cases, hemispheres, dateline, partial windows, UBSan");
    return 0;
}
'''

with tempfile.TemporaryDirectory() as name:
    temp = Path(name)
    (temp / "n32l40x.h").write_text("#include <stdint.h>\n")
    source = temp / "math.c"
    source.write_text(HARNESS)
    exe = temp / "math.exe"
    subprocess.run([shutil.which("gcc"), "-std=c99", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=undefined", "-fsanitize-undefined-trap-on-error",
                    "-I", str(temp), "-I", str(ROOT), "-I", str(ROOT / "include"),
                    str(source), "-lm", "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
