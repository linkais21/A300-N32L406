#ifndef HUADA_ACK_TRIAL_H
#define HUADA_ACK_TRIAL_H
#include <stdbool.h>
#include <stdint.h>

typedef enum {
    HUADA_ACK_IDLE, HUADA_ACK_WAIT, HUADA_ACK_OK, HUADA_ACK_NAK,
    HUADA_ACK_TIMEOUT, HUADA_ACK_CANCELLED, HUADA_ACK_TX_ERROR
} huada_ack_state_t;
typedef struct {
    uint32_t started_ms, timeout_ms;
    huada_ack_state_t state;
    uint8_t message_id;
} huada_ack_t;

/* Isolated trial, main-loop only. Zero initialize before first use.
 * TX must be bounded and must not recursively invoke this transaction.
 * The caller retains the frame only for the duration of start().
 * receive() accepts a COMPLETE binary frame from a separate RX demultiplexer;
 * it does not consume NMEA or assemble UART fragments. No automatic retry.
 */
bool huada_ack_start(huada_ack_t *s, const uint8_t *frame, uint16_t len,
                     uint32_t now, uint32_t timeout,
                     int (*tx)(const uint8_t *, uint16_t));
void huada_ack_receive(huada_ack_t *s, const uint8_t *frame, uint16_t len,
                       uint32_t now);
void huada_ack_poll(huada_ack_t *s, uint32_t now);
void huada_ack_cancel(huada_ack_t *s);
#endif
