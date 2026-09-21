"""Exercise real AT/URC guards; this is path evidence, not a whole-stack proof."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

from test_ec800m_dma_wrap import PREFIX, HEADERS

ROOT = Path(__file__).resolve().parents[2]
HARNESS = PREFIX + r'''
#include <string.h>
#include "ec800m.c"

static unsigned commands;
static bool timeout_reply;
static bool inject_nested;

static void feed(const char *text)
{
    unsigned wr = (EC800M_RX_BUF_SIZE - host_remaining) % EC800M_RX_BUF_SIZE;
    while (*text) {
        EC800M_RX_BUF[wr] = (uint8_t)*text++;
        wr = (wr + 1U) % EC800M_RX_BUF_SIZE;
    }
    host_remaining = EC800M_RX_BUF_SIZE - wr;
}

static void host_tx(uint8_t data)
{
    if (data != '\n') return;
    ++commands;
    assert(commands < 10U);
    assert(s_at_owner == AT_OWNER_BLOCKING);
    if (inject_nested) {
        assert(s_deferred_urc_processing);
        inject_nested = false;
        feed("+QIOPEN: 1,566\r\n");
    }
    if (!timeout_reply) feed("OK\r\n");
}

static void enqueue_failure(void)
{
    s_tcp[0].state = TCP_STATE_OPENING;
    s_tcp[1].state = TCP_STATE_OPENING;
    feed("+QIOPEN: 0,566\r\n");
    drain_rx();
    assert(commands == 0U && s_deferred_urc_count == 1U);
}

int main(int argc, char **argv)
{
    assert(argc == 2);
    host_remaining = EC800M_RX_BUF_SIZE;
    if (!strcmp(argv[1], "owner")) {
        enqueue_failure();
        s_at_owner = AT_OWNER_SMS;
        assert(!at_send_wait("AT", "OK", 10U));
        process_deferred_urc_one();
        assert(commands == 0U && s_deferred_urc_count == 1U);
        assert(s_at_owner == AT_OWNER_SMS && !s_deferred_urc_processing);
        at_owner_release(AT_OWNER_SMS);
        process_deferred_urc_one();
        assert(commands == 1U && !s_deferred_urc_count);
    } else if (!strcmp(argv[1], "nested")) {
        enqueue_failure();
        inject_nested = true;
        process_deferred_urc_one();
        /* The nested wait queued channel 1; it must not recursively execute
         * that command as the first wait releases its owner. */
        assert(commands == 1U && s_deferred_urc_count == 1U);
        assert(s_tcp[0].state == TCP_STATE_CLOSED);
        assert(s_tcp[1].state == TCP_STATE_OPENING);
        assert(!s_deferred_urc_processing && s_at_owner == AT_OWNER_NONE);
        process_deferred_urc_one();
        assert(commands == 2U && !s_deferred_urc_count);
        assert(s_tcp[1].state == TCP_STATE_CLOSED);
        for (unsigned i = 0; i < 8U; ++i) process_deferred_urc_one();
        assert(commands == 2U);
    } else if (!strcmp(argv[1], "timeout")) {
        enqueue_failure();
        timeout_reply = true;
        process_deferred_urc_one();
        assert(g_tick_ms >= 3000U && g_tick_ms <= 3210U);
        assert(s_at_owner == AT_OWNER_NONE && !s_deferred_urc_processing);
        assert(!s_deferred_urc_count && commands == 1U);
        timeout_reply = false;
        assert(at_send_wait("AT", "OK", 10U));
        assert(commands == 2U && s_at_owner == AT_OWNER_NONE);
    } else if (!strcmp(argv[1], "stale")) {
        enqueue_failure();
        ++s_tcp_generation[0];
        process_deferred_urc_one();
        assert(commands == 0U && !s_deferred_urc_count);
        assert(s_tcp[0].state == TCP_STATE_OPENING);
        assert(!s_deferred_urc_processing);
    } else if (!strcmp(argv[1], "busy")) {
        enqueue_failure();
        s_deferred_urc_processing = true;
        process_deferred_urc_one();
        assert(s_deferred_urc_count == 1U && commands == 0U);
        s_deferred_urc_processing = false;
        s_qird_pass_active = true;
        process_deferred_urc_one();
        assert(s_deferred_urc_count == 1U && commands == 0U);
        s_qird_pass_active = false;
        s_udp.state = UDP_TXN_WAIT_PROMPT;
        process_deferred_urc_one();
        assert(s_deferred_urc_count == 1U && commands == 0U);
        s_udp.state = UDP_TXN_IDLE;
        process_deferred_urc_one();
        assert(s_deferred_urc_count == 0U && commands == 1U);
    } else if (!strcmp(argv[1], "capacity")) {
        for (unsigned i = 0; i < AT_DEFERRED_URC_MAX + 4U; ++i)
            defer_urc("+QIURC: \"recv\",0");
        assert(s_deferred_urc_count == AT_DEFERRED_URC_MAX);
        for (unsigned i = 0; i < AT_DEFERRED_URC_MAX; ++i) {
            process_deferred_urc_one();
            assert(s_deferred_urc_count == AT_DEFERRED_URC_MAX - i - 1U);
        }
        assert(commands == 0U && s_tcp_qird_pending_mask == 1U);
        process_deferred_urc_one();
        assert(!s_deferred_urc_count && !s_deferred_urc_processing);
    } else assert(0);
    puts("PASS");
    return 0;
}
'''


def main():
    cc = os.environ.get("CC") or shutil.which("gcc") or shutil.which("cc")
    assert cc, "host C compiler required"
    source = (ROOT / "src/ec800m.c").read_text(encoding="utf-8")
    cases = ("owner", "nested", "timeout", "stale", "busy", "capacity")
    mutations = (
        ("reentry", "s_deferred_urc_processing || s_qird_pass_active",
         "s_qird_pass_active", "nested"),
        ("owner", "bool ok;\n    if (!at_owner_acquire(AT_OWNER_BLOCKING)) return false;",
         "bool ok;\n    (void)at_owner_acquire(AT_OWNER_BLOCKING);", "owner"),
        ("generation", "if(!obsolete)process_urc(line);",
         "(void)obsolete;process_urc(line);", "stale"),
    )
    with tempfile.TemporaryDirectory(prefix="ec800m_stack_reentry_") as td:
        p = Path(td)
        for name, content in HEADERS.items():
            (p / name).write_text(content, encoding="ascii")
        (p / "harness.c").write_text(HARNESS, encoding="ascii")
        cmd = [cc, "-std=c99", "-O1", "-Wall", "-Wextra", "-Werror",
               "-Wno-dangling-else", "-ffunction-sections", "-fdata-sections",
               "-I", str(p), "-I", str(ROOT / "include"),
               str(p / "harness.c"), str(ROOT / "src/ec800m_at_response.c"),
               "-Wl,--gc-sections", "-o", str(p / "harness.exe")]
        variants = [("production", source, cases)]
        for name, old, new, case in mutations:
            assert source.count(old) == 1, f"mutation site changed: {name}"
            variants.append((name, source.replace(old, new, 1), (case,)))
        for name, text, run_cases in variants:
            (p / "ec800m.c").write_text(text, encoding="utf-8")
            build = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            assert build.returncode == 0, build.stderr
            for case in run_cases:
                run = subprocess.run([str(p / "harness.exe"), case],
                                     capture_output=True, text=True, timeout=5)
                if name == "production":
                    assert run.returncode == 0, f"{case}: {run.stderr}"
                    print(f"{case}: PASS")
                else:
                    # A crash/timeout is not accepted as assertion sensitivity.
                    assert run.returncode != 0 and "Assertion" in run.stderr, run.stderr
                    print(f"mutation {name}: REJECTED by {case} assertion")


if __name__ == "__main__":
    main()
