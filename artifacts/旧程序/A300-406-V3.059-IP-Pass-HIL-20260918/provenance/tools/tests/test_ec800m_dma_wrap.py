"""Compile the real modem driver; bound every subprocess to catch RX hangs."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

from test_ec800m_identity_recovery import HARNESS as STUBS
from test_ec800m_ntp_sync import HEADERS

ROOT = Path(__file__).resolve().parents[2]
PREFIX = STUBS.split("typedef enum {")[0].replace(
    "return 1024U;", "return host_remaining;")
PREFIX = PREFIX.replace("volatile uint32_t g_tick_ms;",
                        "static unsigned host_remaining;\nvolatile uint32_t g_tick_ms;")
PREFIX = PREFIX.replace("void USART_SendData(usart_module_t *u, uint16_t data)",
                        "static void host_tx(uint8_t data);\nvoid USART_SendData(usart_module_t *u, uint16_t data)")
PREFIX = PREFIX.replace("(void)u; (void)data;", "(void)u; host_tx((uint8_t)data);")
HARNESS = PREFIX + r'''
#include <string.h>
#include "ec800m.c"

static unsigned qird_reply;
static void host_tx(uint8_t data)
{
    if (qird_reply && data == '\n') {
        /* Binary body plus complete header/tail, ending exactly at DMA wrap. */
        static const uint8_t reply[] = "+QIRD: 5\r\n\x7e\x00\x0d\x0a\x7e\r\nOK\r\n";
        unsigned size = sizeof reply - 1U;
        s_rx_rd = qird_reply == 1U ? 1024U - size : 1020U;
        unsigned wr = s_rx_rd;
        for (unsigned i = 0; i < size; ++i) {
            EC800M_RX_BUF[wr] = reply[i];
            wr = (wr + 1U) % 1024U;
        }
        host_remaining = wr ? 1024U - wr : 0U;
        qird_reply = 0U;
    }
}

static void feed_at(unsigned start, const char *text, bool zero_at_wrap)
{
    s_rx_rd = start;
    unsigned wr = start;
    for (const char *p = text; *p; ++p) {
        EC800M_RX_BUF[wr] = (uint8_t)*p;
        wr = (wr + 1U) % EC800M_RX_BUF_SIZE;
    }
    host_remaining = wr == 0U && zero_at_wrap ? 0U : EC800M_RX_BUF_SIZE - wr;
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    memset(EC800M_RX_BUF, '\r', sizeof EC800M_RX_BUF);
    host_remaining = 0U;
    if (!strcmp(argv[1], "drain")) {
        drain_rx();
        assert(s_rx_rd == 0U);
        /* End exactly on index zero, then straddle the wrap. */
        const char *line = "+CSQ: 27,0\r\n";
        feed_at(1024U - strlen(line), line, true);
        drain_rx(); assert(s_csq == 27 && s_rx_rd == 0U);
        feed_at(1020U, "+CSQ: 18,0\r\n", false);
        drain_rx(); assert(s_csq == 18);
        /* Reload and empty snapshots are both index zero. */
        s_rx_rd = 0U; host_remaining = 1024U; drain_rx();
        assert(s_rx_rd == 0U);
        host_remaining = 1025U; drain_rx(); assert(s_rx_rd == 0U);
        host_remaining = 65535U; drain_rx(); assert(s_rx_rd == 0U);
        for (unsigned i = 0; i < 10000U; ++i) {
            feed_at(1012U, "+CSQ: 23,0\r\n", (i & 1U) != 0U);
            drain_rx(); assert(s_csq == 23 && s_rx_rd == 0U);
        }
    } else if (!strcmp(argv[1], "response")) {
        assert(!at_send_wait_owned("", "OK", 10U));
        assert(g_tick_ms >= 10U && g_tick_ms < 20U);
        feed_at(1020U, "OK\r\n", true);
        assert(at_send_wait_owned("", "OK", 10U));
        feed_at(1022U, "ERROR\r\n", false);
        assert(!at_send_wait_owned("", "OK", 10U));
    } else if (!strcmp(argv[1], "prompt")) {
        assert(!at_wait_prompt_owned("AT", 10U));
        feed_at(1023U, ">", true);
        assert(at_wait_prompt_owned("AT", 10U));
        assert(s_rx_rd == 0U);
    } else if (!strcmp(argv[1], "qird")) {
        const uint8_t *payload = NULL;
        uint16_t length = 0U;
        ec800m_qird_diag_t diag = {0};
        assert(!qird_collect_payload(0U, 10U, &payload, &length, &diag, 10U));
        assert(g_tick_ms < 1000U && s_at_owner == AT_OWNER_NONE);
        for (unsigned mode = 1; mode <= 2; ++mode) {
            qird_reply = mode;
            assert(qird_collect_payload(0U, 10U, &payload, &length, &diag, 10U));
            assert(length == 5U && !memcmp(payload, "\x7e\x00\x0d\x0a\x7e", 5U));
            assert(s_at_owner == AT_OWNER_NONE);
        }
    } else if (!strcmp(argv[1], "discard")) {
        s_tcp[0].state = TCP_STATE_OPENING;
        process_urc("+QIOPEN: 0,566");
        assert(s_rx_rd == 0U && s_tcp[0].state == TCP_STATE_CLOSED);
        drain_rx();
    } else assert(0);
    puts("PASS");
    return 0;
}
'''


def main():
    cc = os.environ.get("CC") or shutil.which("gcc") or shutil.which("cc")
    assert cc, "host C compiler required"
    failures = []
    with tempfile.TemporaryDirectory(prefix="ec800m_dma_wrap_") as td:
        p = Path(td)
        for name, content in HEADERS.items():
            (p / name).write_text(content, encoding="ascii")
        (p / "harness.c").write_text(HARNESS, encoding="ascii")
        cmd = [cc, "-std=c99", "-O1", "-Wall", "-Wextra", "-Werror",
               "-Wno-dangling-else", "-ffunction-sections", "-fdata-sections",
               "-I", str(p), "-I", str(ROOT / "include"), "-I", str(ROOT / "src"),
               str(p / "harness.c"), str(ROOT / "src/ec800m_at_response.c"),
               "-Wl,--gc-sections", "-o", str(p / "harness.exe")]
        built = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        assert built.returncode == 0, built.stderr
        for case in ("drain", "response", "prompt", "qird", "discard"):
            try:
                run = subprocess.run([str(p / "harness.exe"), case],
                                     capture_output=True, text=True, timeout=3)
                if run.returncode:
                    failures.append(f"{case}: exit={run.returncode} {run.stderr}")
                else:
                    print(f"{case}: PASS")
            except subprocess.TimeoutExpired:
                failures.append(f"{case}: TIMEOUT (RX loop did not return)")
        assert not failures, "\n".join(failures)


if __name__ == "__main__":
    main()
