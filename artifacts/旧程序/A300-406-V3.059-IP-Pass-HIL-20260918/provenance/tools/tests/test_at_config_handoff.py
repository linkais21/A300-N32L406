"""Actual serial ingress with deterministic ISR injection during slot copying."""
import pathlib
import subprocess
import tempfile

import test_at_config_serial_f39 as serial

ROOT = serial.ROOT

EXTRA = r'''
#include "f39_command.h"
static int inject_at = -1;
static const char *inject_text;
static bool inject_parse;
static void feed(const char *s) { while (*s) at_config_feed((uint8_t)*s++); }
f39_result_t handoff_parse(const uint8_t *data, uint16_t len, f39_request_t *out) {
    if (inject_parse) {
        inject_parse = false;
        feed("TIMER=66,88\r");
    }
    return f39_parse(data, len, out);
}

/* Replace only the library copy operation, retaining the production ingress,
 * ownership checks, parsers and dispatch. Inject at each byte boundary. */
char *handoff_strncpy(char *dst, const char *src, size_t n) {
    size_t i;
    bool end = false;
    for (i = 0; i <= n; ++i) {
        if (inject_at == (int)i) {
            inject_at = -1;
            feed(inject_text);
        }
        if (i == n) break;
        if (!end && src[i] == 0) end = true;
        dst[i] = end ? 0 : src[i];
    }
    return dst;
}

int main(void) {
    unsigned i;
    config.gnss_type = GNSS_TYPE_TAU804M;
    at_config_init();
    line("TIMER=45,90");
    assert(config.report_moving_s == 45);

    /* First committed line wins; busy input cannot replace it. */
    feed("TIMER=11,22\rTIMER=33,44\n");
    at_config_process();
    assert(config.report_moving_s == 11 && config.report_stopped_s == 22);
    at_config_process();
    assert(config.report_moving_s == 11);

    /* Drop a busy line through its delimiter, even after slot release. */
    feed("TIMER=12,24\nJUNK");
    at_config_process();
    feed("TIMER=99,99\r\n");
    at_config_process();
    assert(config.report_moving_s == 12);
    line("TIMER=13,26");
    assert(config.report_moving_s == 13);

    /* A new line can queue during parsing, but cannot replace the fallback. */
    feed("TIMER=16,32\r");
    inject_parse = true;
    at_config_process();
    assert(!inject_parse);
    assert(config.report_moving_s == 16 && config.report_stopped_s == 32);
    at_config_process();
    assert(config.report_moving_s == 66 && config.report_stopped_s == 88);

    for (i = 0; i <= 127; ++i) {
        feed("TIMER=14,28\r");
        inject_text = "TIMER=77,88\r";
        inject_at = (int)i;
        console_len = 0; console[0] = 0;
        at_config_process();
        assert(inject_at == -1);
        assert(config.report_moving_s == 14 && config.report_stopped_s == 28);
        at_config_process();
        assert(config.report_moving_s == 14);

        feed("VIBSENS,20#\n");
        inject_at = (int)i;
        console_len = 0; console[0] = 0;
        at_config_process();
        assert(inject_at == -1);
        assert(config.vib_sens == 20);
        assert(strstr(console, "VIBSENS=Success!") != NULL);
    }

    /* Empty lines, maximum capacity and existing truncation stay bounded. */
    feed("\r\n\n"); at_config_process();
    for (i = 0; i < 127; ++i) at_config_feed('X');
    at_config_feed('\n');
    console_len = 0; console[0] = 0; at_config_process();
    assert(strstr(console, "ERR:UNKNOWN CMD") != NULL);
    for (i = 0; i < 300; ++i) at_config_feed('X');
    at_config_feed('\r');
    console_len = 0; console[0] = 0; at_config_process();
    assert(strstr(console, "ERR:UNKNOWN CMD") != NULL);
    line("TIMER=15,30");
    assert(config.report_moving_s == 15 && config.report_stopped_s == 30);
    return 0;
}
'''


def test_handoff():
    cc = serial.compiler()
    assert cc, "host GCC is required"
    with tempfile.TemporaryDirectory(prefix="at_handoff_") as directory:
        tmp = pathlib.Path(directory)
        (tmp / "h.c").write_text(serial.HARNESS.split("int main(void) {")[0] + EXTRA,
                                 encoding="ascii")
        (tmp / "n32l40x.h").write_text(
            "#define GPIOA ((void*)0)\n#define GPIO_PIN_12 12U\n"
            "#define Bit_RESET 0\nint GPIO_ReadInputDataBit(void*,unsigned);\n"
            "void NVIC_SystemReset(void);\n", encoding="ascii")
        sources = ["f39_command", "f39_config_adapter", "f39_reply",
                   "sms_command", "terminal_identity"]
        for optimization in ([], ["-Os", "-flto"]):
            subprocess.run(
                [cc, "-std=c99", "-Wall", "-Wextra", "-Werror", *optimization,
                 "-Dstrncpy=handoff_strncpy", "-Df39_parse=handoff_parse",
                 "-I", str(tmp), "-I", str(ROOT / "include"),
                 "-c", str(ROOT / "src/at_config.c"), "-o", str(tmp / "at.o")],
                check=True, timeout=60)
            command = [cc, "-std=c99", "-Wall", "-Wextra", "-Werror", *optimization,
                       "-Dstrncpy=handoff_strncpy", "-I", str(tmp),
                       "-I", str(ROOT / "include"), str(tmp / "h.c"),
                       *(str(ROOT / "src" / (s + ".c")) for s in sources),
                       str(tmp / "at.o"), "-lm", "-o", str(tmp / "h.exe")]
            subprocess.run(command, check=True, timeout=60)
            subprocess.run([str(tmp / "h.exe")], check=True, timeout=15)


if __name__ == "__main__":
    test_handoff()
    print("at_config handoff: PASS (busy, partial drop, 256 copy interleavings, boundaries; O0/Os+LTO)")
