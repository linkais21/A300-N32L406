#ifndef EC800M_H
#define EC800M_H

#include <stdint.h>
#include <stdbool.h>

/* TCP channel indices */
#define EC800M_CH_MAIN    0
#define EC800M_CH_OTA     1
#define EC800M_CH_AGPS    2
#define EC800M_CH_BACKUP  3
#define EC800M_CH_NTRIP   4
#define EC800M_CH_MAX     5

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
bool ec800m_is_ready(void);

/* Power control */
void ec800m_power_on(void);
void ec800m_power_off(void);
void ec800m_reset(void);

/* TCP */
int  ec800m_tcp_open(uint8_t ch, const char *ip, uint16_t port);
int  ec800m_tcp_send(uint8_t ch, const uint8_t *data, uint16_t len);
void ec800m_tcp_close(uint8_t ch);
tcp_state_t ec800m_tcp_state(uint8_t ch);

/* Info */
void ec800m_get_imei(char *buf, uint8_t size);
void ec800m_get_iccid(char *buf, uint8_t size);
int  ec800m_get_csq(void);

/* Sleep */
void ec800m_sleep_enable(void);
void ec800m_sleep_disable(void);

/* Register upper-layer receive callback */
void ec800m_register_recv(ec800m_recv_cb_t cb);
/* Dedicated OTA stream callback; channel 1 is not delivered to JT808. */
void ec800m_register_ota_recv(ec800m_recv_cb_t cb);

/* Called from DMA IRQ */
void ec800m_dma_rx_complete(void);

/* Called from USART3 IDLE line IRQ (if used) */
void ec800m_usart_idle(void);

#endif
