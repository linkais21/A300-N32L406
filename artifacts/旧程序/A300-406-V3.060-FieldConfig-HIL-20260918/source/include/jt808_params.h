#ifndef JT808_PARAMS_H
#define JT808_PARAMS_H

#include <stdint.h>

/*
 * JT808/GB-T 808-2013 standard parameter IDs (0x8103 / 0x8104)
 * Only the subset relevant to this device is handled.
 */

/* Timing */
#define PARAM_HEARTBEAT_INTERVAL   0x0001  /* uint32, seconds */
#define PARAM_TCP_RESP_TIMEOUT     0x0002  /* uint32, seconds */
#define PARAM_TCP_RETRY_COUNT      0x0003  /* uint32 */
#define PARAM_UDP_RESP_TIMEOUT     0x0004  /* uint32, seconds */
#define PARAM_UDP_RETRY_COUNT      0x0005  /* uint32 */
#define PARAM_SMS_RESP_TIMEOUT     0x0006  /* uint32, seconds */
#define PARAM_SMS_RETRY_COUNT      0x0007  /* uint32 */

/* Reporting interval */
#define PARAM_MAIN_SERVER          0x0013  /* string IP or domain, no port */
#define PARAM_BACKUP_SERVER        0x0017  /* string IP or domain */
#define PARAM_TCP_PORT             0x0018  /* DWORD, main TCP port; FIP remains independent */
#define PARAM_SERVER_APN           0x0010  /* string */
#define PARAM_SERVER_APN_USER      0x0011  /* string */
#define PARAM_SERVER_APN_PASS      0x0012  /* string */

#define PARAM_REPORT_STRATEGY       0x0020 /* DWORD, only 0: periodic */
#define PARAM_REPORT_SCHEME         0x0021 /* DWORD, only 0: ACC based */
#define PARAM_REPORT_INTERVAL_NOACC 0x0027 /* DWORD, sleep/stopped seconds */
#define PARAM_REPORT_INTERVAL_DEFAULT 0x0029 /* DWORD, default/moving seconds */
#define PARAM_MILEAGE              0x0080 /* DWORD, 0.1 km */
#define PARAM_PROVINCE             0x0081 /* WORD */
#define PARAM_CITY                 0x0082 /* WORD */
#define PARAM_PLATE                0x0083 /* STRING, GBK bytes */
#define PARAM_PLATE_COLOR          0x0084 /* BYTE */

/* Alarms */
#define PARAM_SPEED_LIMIT          0x0055  /* uint32, km/h */
#define PARAM_SPEED_LIMIT_TIME     0x0056  /* uint32, seconds */
#define PARAM_CONT_DRIVE_TIME      0x0057  /* uint32, minutes */
#define PARAM_DRIVE_DAY_TIME       0x0058  /* uint32, minutes */
#define PARAM_MIN_REST_TIME        0x0059  /* uint32, minutes */

/* Platform phone number */
#define PARAM_PLATFORM_PHONE       0x0040  /* string */
#define PARAM_PLATFORM_SMS         0x0041  /* string */

/* Monitoring */
#define PARAM_MONITOR_PHONE        0x0042  /* string */
#define PARAM_MONITOR_SMS          0x0043  /* string */

void jt808_params_handle_set(const uint8_t *body, uint16_t len, uint16_t sn);
void jt808_params_handle_query(const uint8_t *body, uint16_t len, uint16_t sn);
void jt808_params_handle_info_query(uint16_t sn);   /* 0x8107 */

#endif
