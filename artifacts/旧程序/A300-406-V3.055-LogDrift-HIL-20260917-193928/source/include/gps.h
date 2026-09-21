#ifndef GPS_H
#define GPS_H

#include <stdint.h>
#include <stdbool.h>

typedef struct {
    double   lat;           /* degrees, positive=N */
    double   lon;           /* degrees, positive=E */
    float    speed_kmh;
    float    heading;       /* degrees true */
    float    altitude_m;    /* GGA f[9]: antenna height above MSL, metres */
    float    geoid_sep_m;   /* GGA f[11]: geoid separation, metres */
    uint8_t  fix_quality;   /* 0=invalid 1=GPS 2=DGPS 4=RTK */
    uint8_t  satellites;
    float    hdop;
    uint16_t year;
    uint8_t  month;
    uint8_t  day;
    uint8_t  hour;
    uint8_t  minute;
    uint8_t  second;
    bool     valid;
    uint32_t last_update_ms;
    uint32_t heading_update_ms; /* updated only by a valid RMC sentence */
} gps_data_t;

typedef struct {
    uint32_t rx_bytes;
    uint32_t sentences;
    uint32_t gga;
    uint32_t rmc;
    uint32_t parsed;
    uint32_t checksum_fail;
    uint32_t format_fail;
    uint32_t no_fix;
    uint32_t drop;
    uint32_t drop_queue;  /* queue full at sentence start */
    uint32_t drop_length; /* overlength while capturing a sentence */
    uint32_t overrun;     /* UART OREF observed; not a sentence count */
    uint32_t gsv_seen;    /* checksum-valid GSV received by main-loop parser */
    uint32_t gsv_complete;
} gps_diag_t;

void gps_init(void);
typedef struct {
    uint8_t satellites, average, maximum;
    uint32_t sequence;
} gps_quality_t;
/* Complete, recent GSV cycles only. False clears the output. */
bool gps_get_quality(gps_quality_t *out);
bool gps_quality_fix_fresh(void);
bool gps_is_enabled(void);
void gps_enable(bool en);           /* power gate via GPS_EN */
void gps_process(void);             /* call from main loop  */
/* Bounded local diagnostic trace; at most 32 sentences within five seconds. */
void gps_trace_start(void);
bool gps_is_valid(void);
const gps_data_t *gps_get_data(void);
/* Preserve a fresh, valid fix before GNSS is powered down for STOP1. */
bool gps_capture_last_trusted(void);
/* Capture an already selected live report; caller owns the snapshot. */
bool gps_capture_last_trusted_snapshot(const gps_data_t *snapshot);
bool gps_get_last_trusted(gps_data_t *out);
/* Advance the retained fix timestamp across a STOP1 sleep interval while
 * preserving its coordinates for historical 0x0200 reports. */
void gps_advance_last_trusted_seconds(uint32_t elapsed_seconds);
/* Reapply the required NMEA output setup after STOP1 wake without clearing
 * the retained STOP1 position. */
void gps_resume_after_wake(void);
/* Correct the retained STOP1 fix's clock from an external UTC time source
 * (NTP). No-op unless a trusted fix already exists; never touches
 * lat/lon/speed/heading/altitude/fix_quality. */
void gps_apply_ntp_utc(uint16_t year, uint8_t month, uint8_t day,
                       uint8_t hour, uint8_t minute, uint8_t second);
const volatile gps_diag_t *gps_get_diag(void);

/* Called from UART4_IRQHandler */
void gps_rx_isr(uint8_t byte);

/* Send CASIC command to GPS module */
void gps_send_cmd(const char *cmd);
int gps_send_raw(const uint8_t *data, uint32_t len);
typedef gps_data_t gps_context_t;

#endif
