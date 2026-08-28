#ifndef JT808_H
#define JT808_H

#include <stdint.h>
#include <stdbool.h>

/* Message IDs (GB/T 808-2013) */
#define MSG_TERMINAL_GENERAL_RESP   0x0001
#define MSG_HEARTBEAT               0x0002
#define MSG_TERMINAL_REGISTER       0x0100
#define MSG_TERMINAL_REGISTER_RESP  0x8100
#define MSG_TERMINAL_AUTH           0x0102
#define MSG_SET_TERMINAL_PARAM      0x8103
#define MSG_QUERY_TERMINAL_PARAM    0x8104
#define MSG_QUERY_TERMINAL_INFO     0x8107
#define MSG_TERMINAL_CTRL           0x8105
#define MSG_LOCATION_REPORT         0x0200
#define MSG_BLIND_ZONE_BATCH        0x0704
#define MSG_LOCATION_QUERY_RESP     0x0201
#define MSG_LOCATION_QUERY          0x8201
#define MSG_TEMP_LOCATION_TRACK     0x8202
#define JT808_REPORT_INTERVAL_MIN_S 5U
#define MSG_TEXT_MESSAGE            0x8300
#define MSG_SET_POLYGON_AREA        0x8604
#define MSG_PLATFORM_GENERAL_RESP   0x8001

/* Location status flags (word 1) — 808-2013 Table 4
 * bit2: 0=East lon, 1=West lon
 * bit3: 0=North lat, 1=South lat */
#define LOC_FLAG_ACC_ON     (1u << 0)
#define LOC_FLAG_GPS_FIXED  (1u << 1)
#define LOC_FLAG_WEST_LON   (1u << 2)   /* 0=East(默认), 1=West */
#define LOC_FLAG_SOUTH_LAT  (1u << 3)   /* 0=North(默认), 1=South */
#define LOC_FLAG_OPERATING  (1u << 4)
#define LOC_FLAG_ENCRYPTED  (1u << 5)

/* Alarm flags */
#define ALM_EMERGENCY_SOS   (1u << 0)
#define ALM_OVERSPEED       (1u << 1)
#define ALM_FATIGUE_DRIVING (1u << 2)
#define ALM_GNSS_FAULT      (1u << 4)
#define ALM_FUEL_CUTOFF     (1u << 9)
#define ALM_POWER_LOW       (1u << 27)
#define ALM_POWER_CUT       (1u << 28)

/* Terminal info for registration */
typedef struct {
    char province_id[3];    /* 2-byte BCD */
    char city_id[3];
    char manufacturer_id[6]; /* 5 bytes */
    char terminal_model[9];  /* 8 bytes */
    char terminal_id[8];     /* 7 bytes */
    uint8_t color;
    char plate_no[13];       /* license plate */
    char phone[12];          /* MSISDN */
    char auth_code[32];
} jt808_terminal_t;

void jt808_init(const jt808_terminal_t *info);
void jt808_process(void);

/* Called when EC800M TCP ch0 or ch3 receives data */
void jt808_on_recv(uint8_t ch, const uint8_t *data, uint16_t len);

/* Build and send messages */
int jt808_send_register(void);
void jt808_request_reregister(void);
int jt808_send_auth(const char *code);
int jt808_send_heartbeat(void);
int jt808_send_location(void);
int jt808_send_general_resp(uint16_t resp_sn, uint16_t resp_id, uint8_t result);
bool jt808_is_online(void);

/* Send an arbitrary message body (used by jt808_params.c for 0x0104/0x0107) */
int jt808_send_raw(uint16_t msg_id, uint16_t resp_sn,
                   const uint8_t *body, uint16_t blen);
int jt808_send_raw_tracked(uint16_t msg_id, const uint8_t *body,
                           uint16_t blen, uint16_t *serial_out);
uint8_t jt808_online_channel(void);
uint32_t jt808_online_generation(void);

/* Server address management */
void jt808_set_server(const char *ip, uint16_t port, bool is_backup);
void jt808_get_server(char *ip_buf, uint16_t *port, bool is_backup);

/* Alarm trigger */
void jt808_trigger_alarm(uint32_t alarm_bit);

/* Get/set heartbeat interval (seconds) */
void jt808_set_heartbeat_s(uint16_t s);
uint16_t jt808_get_heartbeat_s(void);

/* Get/set reporting interval */
void jt808_set_report_interval(uint16_t moving_s, uint16_t stopped_s);

#endif
