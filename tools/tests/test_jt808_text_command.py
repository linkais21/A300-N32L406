#!/usr/bin/env python3
"""Contract for JT808 0x8300 text delivery as a command channel.

The terminal command spec (文档/1_定位终端指令说明V1.0.xlsx sheet1) lists three
delivery paths: SMS, serial, and 0x8300 text delivery. This covers the third.

Per JT/T 808-2013 table 37 the body is a flag byte followed by the text, and
section 7.x says the terminal answers a text delivery with a terminal general
response (0x0001) -- there is no 0x0900 passthrough uplink here, so the reply
text is intentionally dropped and only the result byte reports the outcome.
"""

from pathlib import Path
import subprocess
import sys
import tempfile

import test_jt808_dual_session as dual

ROOT = Path(__file__).resolve().parents[2]

TEXT_MAIN = r'''
/* Records what the 0x8300 handler forwarded to the command executor. This
   overrides the weak default in jt808.c the same way at_config.c does. */
static unsigned exec_calls;
static char exec_text[256];
static bool exec_result = true;

bool at_config_execute_text_command(const uint8_t *text, uint16_t len) {
    ++exec_calls;
    if (len >= sizeof(exec_text)) len = (uint16_t)(sizeof(exec_text) - 1U);
    memcpy(exec_text, text, len);
    exec_text[len] = '\0';
    if (!strcmp(exec_text,"PID,12345678901")) strcpy(cfg.pid,"12345678901");
    return exec_result;
}

static void text_msg(uint8_t ch, uint8_t flag, const char *text) {
    uint8_t body[192];
    size_t n = strlen(text);
    body[0] = flag;
    memcpy(body + 1, text, n);
    inject(ch, 0x8300U, body, (uint16_t)(1U + n));
}

/* Decode the most recent frame on a channel and check it is a terminal general
   response acknowledging 0x8300 with the given result byte. */
static void expect_general_resp(uint8_t ch, uint8_t want_result) {
    uint8_t decoded[1024];
    uint16_t sn, length;
    assert(msg(ch, &sn, decoded, &length) == 0x0001U);
    /* body: resp serial(2) resp id(2) result(1), starting after the 12B header */
    assert(decoded[12] == 0x12U && decoded[13] == 0x34U);
    assert(decoded[14] == 0x83U && decoded[15] == 0x00U);
    assert(decoded[16] == want_result);
}

int main(void) {
    jt808_terminal_t terminal;
    uint8_t decoded[1024];
    uint16_t sn0, sn3, length;
    unsigned before;

    memset(&cfg, 0, sizeof(cfg)); strcpy(cfg.pid, "56789012345");
    cfg.heartbeat_s = 600; cfg.report_moving_s = 30; cfg.report_stopped_s = 60;
    memset(&terminal, 0, sizeof(terminal));
    memcpy(terminal.manufacturer_id, "CYHLL", 5U);
    strcpy(terminal.terminal_model, "A300_406");
    open_ch[0] = open_ch[3] = true; generation[0] = 1U; generation[3] = 7U;
    jt808_init(&terminal); jt808_set_heartbeat_s(600U); jt808_process();
    assert(msg(0U, &sn0, decoded, &length) == 0x0100U);
    assert(msg(3U, &sn3, decoded, &length) == 0x0100U);
    reg_resp(0U, sn0, "MAIN-AUTH"); jt808_process();
    assert(msg(0U, &sn0, decoded, &length) == 0x0102U);
    reg_resp(3U, sn3, "BACK-AUTH"); jt808_process();
    assert(msg(3U, &sn3, decoded, &length) == 0x0102U);
    auth_resp(0U, sn0, 0U); auth_resp(3U, sn3, 0U);
    assert(jt808_online_mask() == 0x09U);

    /* A command arrives with the flag byte stripped and the framing '#'
       removed, matching what the SMS ingress hands to the same executor. */
    exec_calls = 0U; before = sends[0];
    text_msg(0U, 0x04U, "PARAM#");
    assert(exec_calls == 1U && strcmp(exec_text, "PARAM") == 0);
    assert(sends[0] == before + 1U);
    expect_general_resp(0U, 0U);

    /* The trailing '#' is optional. */
    exec_calls = 0U;
    text_msg(0U, 0x04U, "VIBSENS,30");
    assert(exec_calls == 1U && strcmp(exec_text, "VIBSENS,30") == 0);
    expect_general_resp(0U, 0U);

    /* A command the executor rejects is still acknowledged, with result=1. */
    exec_calls = 0U; exec_result = false; before = sends[0];
    text_msg(0U, 0x04U, "BOGUS,1#");
    assert(exec_calls == 1U);
    assert(sends[0] == before + 1U);
    expect_general_resp(0U, 1U);
    exec_result = true;

    /* Flag bits are advisory (display/TTS/advertising screen); the command is
       executed regardless of which presentation bits the platform set. */
    exec_calls = 0U;
    text_msg(0U, 0x01U, "HBT#");
    assert(exec_calls == 1U && strcmp(exec_text, "HBT") == 0);
    expect_general_resp(0U, 0U);

    /* A body carrying only the flag byte, or only "#", has no command in it:
       no executor call, and the frame is refused rather than silently ignored. */
    exec_calls = 0U; before = sends[0];
    inject(0U, 0x8300U, (const uint8_t *)"\x04", 1U);
    assert(exec_calls == 0U);
    assert(sends[0] == before + 1U);
    expect_general_resp(0U, 1U);

    exec_calls = 0U;
    text_msg(0U, 0x04U, "#");
    assert(exec_calls == 0U);
    expect_general_resp(0U, 1U);

    /* An empty body must not underflow the length arithmetic. */
    exec_calls = 0U; before = sends[0];
    query(0U, 0x8300U);
    assert(exec_calls == 0U);
    assert(sends[0] == before + 1U);
    expect_general_resp(0U, 1U);

    /* The backup channel is answered on the channel the command arrived on. */
    exec_calls = 0U; before = sends[0];
    text_msg(3U, 0x04U, "PARAM#");
    assert(exec_calls == 1U);
    assert(sends[0] == before);
    expect_general_resp(3U, 0U);

    /* A PID setter must acknowledge using the original terminal identity. */
    uint8_t old_identity[6];memcpy(old_identity,decoded+4,6);
    /* Read a fresh old-identity response rather than a stale registration. */
    text_msg(0U,0x04U,"PARAM#");msg(0U,&sn0,decoded,&length);
    memcpy(old_identity,decoded+4,6);
    text_msg(0U,0x04U,"PID,12345678901#");expect_general_resp(0U,0U);
    msg(0U,&sn0,decoded,&length);assert(!memcmp(decoded+4,old_identity,6));
    return 0;
}
'''


def main() -> int:
    cc = dual.compiler()
    if not cc:
        return 1
    source = (dual.HARNESS[:dual.HARNESS.index("int main(void) {")] + TEXT_MAIN).replace(
        "static void test_rx_overlap(void)", "void test_rx_overlap(void)")
    with tempfile.TemporaryDirectory(prefix="jt808_text_") as directory:
        t = Path(directory)
        h = t / "h.c"
        b = t / "h.exe"
        h.write_text(source + '\n#include "' + (ROOT/'tools/tests/jt808_host_support.h').as_posix() + '"\n', encoding="ascii")
        (t / "n32l40x.h").write_text(
            "#ifndef N32L40X_H\n#define N32L40X_H\n"
            "#define GPIOA ((void*)0)\n#define GPIO_PIN_12 12U\n"
            "#define Bit_RESET 0\n"
            "int GPIO_ReadInputDataBit(void*,unsigned);\n#endif\n",
            encoding="ascii",
        )
        cmd = [cc, "-std=c99", "-Wall", "-Wextra", "-Werror",
               "-I", str(t), "-I", str(ROOT / "include"), str(h),
               str(ROOT / "src/plate_encoding.c"), str(ROOT / "src/jt808.c"), str(ROOT / "src/jt808_session.c"),
               str(ROOT / "src/terminal_identity.c"), "-lm", "-o", str(b)]
        x = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
        if x.returncode:
            print(x.stdout + x.stderr, end="")
            return x.returncode
        x = subprocess.run([str(b)], cwd=ROOT, capture_output=True, text=True)
        if x.returncode:
            print(x.stdout + x.stderr, end="")
            return x.returncode
    print("test_jt808_text_command: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
