#!/usr/bin/env python3
from pathlib import Path
import subprocess
import sys
import tempfile

import test_jt808_dual_session as dual

ROOT = Path(__file__).resolve().parents[2]

MAIN = r'''
int main(void)
{
    jt808_terminal_t terminal;
    uint8_t decoded[1024];
    uint16_t sn0, sn3, length;
    unsigned before0, before3;

    (void)reg_resp;
    (void)query;

    memset(&cfg, 0, sizeof(cfg));
    strcpy(cfg.pid, "56789012345");
    strcpy(cfg.auth_code, "MAIN-AUTH");
    strcpy(cfg.backup_auth_code, "BACK-AUTH");
    cfg.heartbeat_s = 600U;
    memset(&terminal, 0, sizeof(terminal));
    open_ch[0] = open_ch[3] = true;
    generation[0] = 1U;
    generation[3] = 7U;
    terminal_info_result = JT808_TERMINAL_INFO_OK;

    jt808_init(&terminal);
    jt808_process();
    assert(msg(0U, &sn0, decoded, &length) == 0x0102U);
    assert(msg(3U, &sn3, decoded, &length) == 0x0102U);
    auth_resp(0U, sn0, 0U);
    auth_resp(3U, sn3, 0U);
    before0 = sends[0]; before3 = sends[3];
    jt808_process();
    assert(sends[0] == before0 + 1U && sends[3] == before3 + 1U);
    assert(msg(0U, &sn0, decoded, &length) == 0x0107U);
    assert(length == 14U && decoded[12U] == 0xA5U);
    assert(msg(3U, &sn3, decoded, &length) == 0x0107U);
    before0 = sends[0]; before3 = sends[3];
    jt808_process();
    assert(sends[0] == before0 && sends[3] == before3);
    query(0U, 0x8107U);
    assert(sends[0] == before0 + 1U && sends[3] == before3);
    assert(msg(0U, &sn0, decoded, &length) == 0x0107U);

    open_ch[0] = false; jt808_process();
    open_ch[0] = true; ++generation[0]; jt808_process();
    assert(msg(0U, &sn0, decoded, &length) == 0x0102U);
    auth_resp(0U, sn0, 0U);
    before0 = sends[0]; jt808_process();
    assert(sends[0] == before0);

    before0 = sends[0]; before3 = sends[3];
    jt808_init(&terminal); jt808_process();
    assert(msg(0U, &sn0, decoded, &length) == 0x0102U);
    assert(msg(3U, &sn3, decoded, &length) == 0x0102U);
    auth_resp(0U, sn0, 0U); auth_resp(3U, sn3, 0U); jt808_process();
    assert(sends[0] == before0 + 2U && sends[3] == before3 + 2U);
    assert(msg(0U, &sn0, decoded, &length) == 0x0107U);
    assert(msg(3U, &sn3, decoded, &length) == 0x0107U);

    open_ch[3] = false;
    jt808_init(&terminal); jt808_process();
    assert(msg(0U, &sn0, decoded, &length) == 0x0102U);
    auth_resp(0U, sn0, 0U);
    fail_send[0] = true;
    before0 = sends[0]; jt808_process();
    assert(sends[0] == before0 + 1U);
    before0 = sends[0]; g_tick_ms += 4999U; jt808_process();
    assert(sends[0] == before0);
    g_tick_ms += 1U; jt808_process();
    assert(sends[0] == before0 + 1U);
    before0 = sends[0]; g_tick_ms += 5000U; jt808_process();
    assert(sends[0] == before0 + 1U);
    before0 = sends[0]; g_tick_ms += 59999U; jt808_process();
    assert(sends[0] == before0);
    g_tick_ms += 1U; jt808_process();
    assert(sends[0] == before0 + 1U);

    fail_send[0] = true; ambiguous_send[0] = true;
    jt808_init(&terminal); jt808_process();
    assert(msg(0U, &sn0, decoded, &length) == 0x0102U);
    auth_resp(0U, sn0, 0U);
    before0 = sends[0]; jt808_process();
    assert(sends[0] == before0 + 1U);
    before0 = sends[0]; g_tick_ms += 60000U; jt808_process();
    assert(sends[0] == before0);
    return 0;
}
'''


def main() -> int:
    cc = dual.compiler()
    if not cc:
        return 1
    source = (dual.HARNESS[:dual.HARNESS.index("int main(void) {")] + MAIN).replace(
        "static void test_rx_overlap(void)", "void test_rx_overlap(void)")
    with tempfile.TemporaryDirectory(prefix="jt808_boot_info_") as directory:
        temp = Path(directory)
        harness = temp / "h.c"
        binary = temp / "h.exe"
        harness.write_text(source, encoding="ascii")
        (temp / "n32l40x.h").write_text(
            "#ifndef N32L40X_H\n#define N32L40X_H\n"
            "#define GPIOA ((void*)0)\n#define GPIO_PIN_12 12U\n#define Bit_RESET 0\n"
            "int GPIO_ReadInputDataBit(void*,unsigned);\n#endif\n",
            encoding="ascii",
        )
        command = [
            cc, "-std=c99", "-Wall", "-Wextra", "-Werror",
            "-I", str(temp), "-I", str(ROOT / "include"), str(harness),
            str(ROOT / "src/jt808.c"), str(ROOT / "src/jt808_session.c"),
            str(ROOT / "src/terminal_identity.c"), "-lm", "-o", str(binary),
        ]
        compiled = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        if compiled.returncode:
            print(compiled.stdout + compiled.stderr, end="")
            return compiled.returncode
        executed = subprocess.run([str(binary)], cwd=ROOT, capture_output=True, text=True)
        if executed.returncode:
            print(executed.stdout + executed.stderr, end="")
            return executed.returncode
    print("test_jt808_boot_terminal_info: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
