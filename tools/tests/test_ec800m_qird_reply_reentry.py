"""Replying from inside the TCP receive callback must not corrupt the chunk.

Regression for: qird_collect_payload published its payload as a pointer into
s_at_resp, and jt808_on_recv replies synchronously (0x8103 -> 0x0001 etc.)
through ec800m_tcp_send(), whose SEND OK wait cleared and refilled the same
buffer. A second platform frame in the same QIRD chunk was then overwritten.
"""
import test_ec800m_urc_demux as base

REPLY_HOOK = r'''
static uint8_t seen[64];
static uint16_t seen_len;
static void reply_cb(uint8_t ch, const uint8_t *data, uint16_t len)
{
    assert(ch == 0U && len <= sizeof seen);
    /* Like jt808_on_recv: walk the chunk, reply after the first frame. */
    for (uint16_t i = 0U; i < len; ++i) {
        seen[seen_len++] = data[i];
        if (i == 4U) {
            reply_mode = 1U;
            assert(ec800m_tcp_send(0U, (const uint8_t *)"abc", 3U) == 0);
        }
    }
}
'''

SCENARIO = r'''
    /* Two frames in one QIRD read; the callback replies after the first. */
    {
        static const uint8_t two_frames[10] = {
            0x7e, 0x81, 0x03, 0x11, 0x7e, 0x7e, 0x83, 0x00, 0x22, 0x7e
        };
        ec800m_test_set_tcp_open(0U);
        ec800m_register_recv(reply_cb);
        seen_len = 0U;
        qird_phase = 20U;
        host_feed_rx("\r\n+QIURC: \"recv\",0\r\n");
        ec800m_process();
        ec800m_process();
        assert(qird_phase == 22U && reply_mode == 3U);
        assert(seen_len == sizeof two_frames);
        assert(memcmp(seen, two_frames, sizeof two_frames) == 0);
        puts("qird reply reentry: PASS");
    }

    puts("test_ec800m_urc_demux: PASS");'''

TX_HOOK = r'''    } else if (qird_phase == 20U && byte == '\n' && strstr(tx_log, "AT+QIRD=0,10\r\n") != NULL) {
        static const uint8_t frames[] = {
            '+','Q','I','R','D',':',' ','1','0','\r','\n',
            0x7e, 0x81, 0x03, 0x11, 0x7e, 0x7e, 0x83, 0x00, 0x22, 0x7e,
            '\r','\n','O','K','\r','\n'
        };
        host_feed_bytes(frames, sizeof frames);
        qird_delivered += 10U;
        qird_phase = 21U;
    } else if (reply_mode == 1U && byte == '\n' && strstr(tx_log, "AT+QISEND=0,3\r\n") != NULL) {
        host_feed_rx(">\r\n");
        reply_mode = 2U;
    } else if (reply_mode == 2U && byte == 'c') {
        /* A long modem result fills the AT response area. */
        host_feed_rx("\r\n+QIURC: \"pdpdeact-noise-padding-padding-padding-padding\",9\r\n"
                     "+CSQ: 20,99\r\n+CSQ: 21,99\r\n+CSQ: 22,99\r\n+CSQ: 23,99\r\n"
                     "+CSQ: 24,99\r\n+CSQ: 25,99\r\n+CSQ: 26,99\r\nSEND OK\r\n");
        reply_mode = 3U;
        qird_phase = 22U;
    } else if (qird_phase == 1U && byte == '\n' && strstr(tx_log, "AT+QIRD=0,") != NULL) {'''


def build_harness() -> str:
    h = base.HARNESS
    anchor = "static void tcp_cb(uint8_t ch, const uint8_t *data, uint16_t len)"
    assert h.count(anchor) == 1
    h = h.replace(anchor, REPLY_HOOK + "\n" + anchor)
    old_counter = "qird_phase == 10U ? EC800M_QIRD_CHUNK : 0U;"
    assert h.count(old_counter) == 1
    h = h.replace(old_counter, "qird_phase == 10U ? EC800M_QIRD_CHUNK :\n                          qird_phase == 20U ? 10U : 0U;")
    old_tx = TX_HOOK.splitlines()[-1]
    assert h.count(old_tx) == 1, "tx anchor"
    h = h.replace(old_tx, TX_HOOK)
    # reply_mode is used by host_uart_tx, which precedes the callback.
    decl = "static unsigned qird_delivered;"
    assert h.count(decl) == 1
    h = h.replace(decl, decl + "\nstatic unsigned reply_mode;")
    end = "\n    puts(\"test_ec800m_urc_demux: PASS\");"
    assert h.count(end) == 1
    return h.replace(end, SCENARIO)


if __name__ == "__main__":
    base.HARNESS = build_harness()
    base.main()
