#ifndef EC800M_H
#define EC800M_H

#include <stdint.h>
#include <stdbool.h>

/* TCP channel indices */
#define EC800M_CH_MAIN    0
#define EC800M_CH_OTA     1
#define EC800M_CH_AGPS    2
#define EC800M_CH_BACKUP  3
#define EC800M_CH_MAX     4

typedef enum {
    EC800M_STATE_OFF = 0,
    EC800M_STATE_BOOTING,
    EC800M_STATE_INIT,
    EC800M_STATE_SIM_CHECK,
    EC800M_STATE_NETWORK_REG,
    EC800M_STATE_PDP_ACTIVE,
    EC800M_STATE_READY,
    EC800M_STATE_ERROR,
} ec800m_state_t;

typedef enum {
    EC800M_FAILURE_NONE = 0,
    EC800M_FAILURE_SIM_QUERY,
    EC800M_FAILURE_NETREG_QUERY,
    EC800M_FAILURE_PDP_ACTIVATE,
    EC800M_FAILURE_PDP_QUERY,
} ec800m_failure_t;

typedef enum {
    TCP_STATE_CLOSED = 0,
    TCP_STATE_OPENING,
    TCP_STATE_OPEN,
    TCP_STATE_ERROR,
} tcp_state_t;

typedef struct {
    char     ip[64];
    uint16_t port;
    tcp_state_t state;
    uint32_t last_connect_ms;
    uint32_t reconnect_delay_ms;
} tcp_channel_t;

/* Callbacks filled in by upper layers */
typedef void (*ec800m_recv_cb_t)(uint8_t ch, const uint8_t *data, uint16_t len);

void ec800m_init(void);
void ec800m_process(void);          /* call from main loop */

ec800m_state_t ec800m_get_state(void);
ec800m_failure_t ec800m_get_failure(void);
int ec800m_get_reg_status(void);
const char *ec800m_state_name(ec800m_state_t state);
const char *ec800m_failure_name(ec800m_failure_t failure);
bool ec800m_is_ready(void);

/* Power control */
void ec800m_power_on(void);
void ec800m_power_off(void);
void ec800m_reset(void);

/* TCP */
int  ec800m_tcp_open(uint8_t ch, const char *ip, uint16_t port);
int  ec800m_tcp_send(uint8_t ch, const uint8_t *data, uint16_t len);
/* True when the most recent ec800m_tcp_send() failure was a "SEND OK" wait
 * timeout (stage=result): bytes were already confirmed on the wire, so the
 * frame may still have been delivered. False for prompt/payload failures,
 * where nothing was sent. Valid only immediately after a nonzero return. */
bool ec800m_tcp_send_was_ambiguous(void);
/* Clear the ambiguous-failure flag; call before any -1 return that bypassed
 * ec800m_tcp_send() so callers don't read a stale flag from a prior send. */
void ec800m_tcp_send_clear_ambiguous(void);
/* One bounded UDP datagram transaction on the temporary OTA channel. */
int  ec800m_udp_send_once(const char *ip, uint16_t port,
                          const uint8_t *data, uint16_t len);
int  ec800m_udp_txn(const char *ip, uint16_t port,
                    const uint8_t *tx, uint16_t tx_len,
                    uint8_t *rx, uint16_t rx_cap, uint32_t timeout_ms);
int  ec800m_udp_txn_start(const char *ip, uint16_t port,
                          const uint8_t *tx, uint16_t tx_len,
                          uint8_t *rx, uint16_t rx_cap, uint32_t timeout_ms);
void ec800m_udp_txn_process(void);
int  ec800m_udp_txn_result(void);
/* Largest SMS reply body the modem layer will accept. Bodies longer than one
 * GSM-7 short message are segmented into a concatenated message. */
#define EC800M_SMS_TEXT_MAX   256U
#define EC800M_SMS_SEGMENT_MAX 153U

int  ec800m_sms_send(const char *phone, const char *text);
void ec800m_tcp_close(uint8_t ch);
tcp_state_t ec800m_tcp_state(uint8_t ch);

/* Info */
void ec800m_get_imei(char *buf, uint8_t size);
void ec800m_get_iccid(char *buf, uint8_t size);
int  ec800m_get_csq(void);

/* Network time (NTP), UTC after applying the modem-reported timezone offset */
typedef struct {
    uint16_t year;
    uint8_t  month, day, hour, minute, second;
    bool     valid;
} ec800m_time_t;
/* Blocking AT+QNTP query against a hardcoded default server; converts the
 * modem's local-time result to UTC. Call only when ec800m_is_ready(). */
bool ec800m_ntp_sync(ec800m_time_t *out);

/* Sleep */
void ec800m_sleep_enable(void);
void ec800m_sleep_disable(void);

/* Register upper-layer receive callback */
void ec800m_register_recv(ec800m_recv_cb_t cb);
/* Dedicated OTA stream callback; channel 1 is not delivered to JT808. */
void ec800m_register_ota_recv(ec800m_recv_cb_t cb);
void ec800m_register_agnss_recv(ec800m_recv_cb_t cb);

/* Called from DMA IRQ */
void ec800m_dma_rx_complete(void);

/* Called from USART3 IDLE line IRQ (if used) */
void ec800m_usart_idle(void);

#endif
