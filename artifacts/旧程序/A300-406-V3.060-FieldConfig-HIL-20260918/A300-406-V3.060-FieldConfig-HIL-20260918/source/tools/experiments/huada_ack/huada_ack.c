#include "huada_ack.h"
#include <stddef.h>

static bool valid_frame(const uint8_t *f, uint16_t n)
{
    uint8_t a = 0, b = 0;
    if (!f || n < 8 || f[0] != 0xf1 || f[1] != 0xd9 ||
        (uint32_t)f[4] + ((uint32_t)f[5] << 8) + 8U != n) return false;
    for (uint16_t i = 2; i < n - 2U; ++i) { a += f[i]; b += a; }
    return a == f[n - 2U] && b == f[n - 1U];
}

bool huada_ack_start(huada_ack_t *s, const uint8_t *f, uint16_t n,
                     uint32_t now, uint32_t timeout,
                     int (*tx)(const uint8_t *, uint16_t))
{
    uint16_t payload;
    if (!s || s->state == HUADA_ACK_WAIT || !tx || !timeout ||
        timeout > INT32_MAX || n > 468U || !valid_frame(f, n) ||
        f[2] != 0x0b) return false;
    payload = n - 8U;
    /* Application guide V1.4: 1..5 satellites, GPS=65 and BDS=92 bytes.
     * Restrict network data to AID messages, never arbitrary CFG commands.
     * Optional TIME/POS must additionally pass freshness checks in caller.
     */
    switch (f[3]) {
    case 0x32: if (!payload || payload > 325 || payload % 65) return false; break;
    case 0x33: if (!payload || payload % 92) return false; break;
    case 0x10: if (payload != 17) return false; break;
    case 0x11: if (payload != 20) return false; break;
    default: return false;
    }
    s->started_ms = now;
    s->timeout_ms = timeout;
    s->message_id = f[3];
    s->state = HUADA_ACK_WAIT;
    if (tx(f, n) != 0) { s->state = HUADA_ACK_TX_ERROR; return false; }
    return true;
}

void huada_ack_poll(huada_ack_t *s, uint32_t now)
{
    if (s && s->state == HUADA_ACK_WAIT &&
        (uint32_t)(now - s->started_ms) >= s->timeout_ms)
        s->state = HUADA_ACK_TIMEOUT;
}

void huada_ack_receive(huada_ack_t *s, const uint8_t *f, uint16_t n,
                       uint32_t now)
{
    huada_ack_poll(s, now);
    if (!s || s->state != HUADA_ACK_WAIT || n != 10 || !valid_frame(f, n) ||
        f[2] != 5 || f[3] > 1 || f[6] != 0x0b || f[7] != s->message_id)
        return;
    s->state = f[3] ? HUADA_ACK_OK : HUADA_ACK_NAK;
}

void huada_ack_cancel(huada_ack_t *s)
{
    if (s) s->state = HUADA_ACK_CANCELLED;
}
