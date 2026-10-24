#ifndef GPS_H
#define GPS_H

#include <stdint.h>
#include <stdbool.h>

/* Fixed-point degrees: 1e-7 deg (~1.1 cm). The FPU is single precision, so
 * coordinates stay integer end to end and no soft-double code is linked. */
#define GPS_E7_PER_DEG   10000000L
#define GPS_LAT_E7_MAX   (90L * GPS_E7_PER_DEG)
#define GPS_LON_E7_MAX   (180L * GPS_E7_PER_DEG)

typedef struct {
    int32_t  lat_e7;        /* 1e-7 degrees, positive=N */
    int32_t  lon_e7;        /* 1e-7 degrees, positive=E */
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
void gps_trusted_store_init(void);
void gps_trusted_store_process(void);
typedef struct {
    uint8_t satellites, average, maximum, cn_threshold, qualified;
    uint32_t sequence;
} gps_quality_t;
/* Complete, recent GSV cycles only. False clears measurements, keeps CNTH. */
bool gps_get_quality(gps_quality_t *out);
/* RAM-only production threshold, 20..50 dB-Hz. A change discards old cycles. */
bool gps_set_quality_cn_threshold(uint8_t threshold);
bool gps_quality_fix_fresh(void);
bool gps_is_enabled(void);
void gps_enable(bool en);           /* power gate via GPS_EN */
void gps_process(void);             /* call from main loop  */
/* Main-loop snapshot of the latest complete ACK frame; checksum is checked
 * by the AGNSS consumer. Sequence changes invalidate a concurrent copy. */
uint32_t gps_agnss_ack_sequence(void);
bool gps_agnss_take_ack(uint32_t *sequence, uint8_t frame[10]);
/* Bounded local diagnostic trace; at most 32 sentences within five seconds. */
void gps_trace_start(void);
bool gps_is_valid(void);
const gps_data_t *gps_get_data(void);
/* Preserve a fresh, valid fix before GNSS is powered down for STOP1. */
bool gps_capture_last_trusted(void);
/* Capture an already selected live report; caller owns the snapshot. */
bool gps_capture_last_trusted_snapshot(const gps_data_t *snapshot);
/* Coordinates stay retained; UTC advances with SysTick even without a fix. */
bool gps_get_last_trusted(gps_data_t *out);
/* Same retained coordinates, but their original acquisition UTC for location
 * reports, with valid=false to prevent use as a live fix. False until a live
 * fix supplies that time; legacy Flash records
 * only saved an advanced clock. Does not fabricate a new position. */
bool gps_get_last_trusted_location(gps_data_t *out);
/* No fix ever acquired: zero position and invalid fix; UTC if synchronized,
 * otherwise an all-zero unknown timestamp. Never creates a trusted fix. */
void gps_get_unfixed_report(gps_data_t *out);
/* Advance the retained fix timestamp across a STOP1 sleep interval while
 * preserving its coordinates for historical 0x0200 reports. Add only time
 * with SysTick stopped; awake/shallow-WFI time is accounted inside gps.c. */
void gps_advance_last_trusted_seconds(uint32_t elapsed_seconds);
/* Reapply the required NMEA output setup after STOP1 wake without clearing
 * the retained STOP1 position. */
void gps_resume_after_wake(void);
/* Correct the retained STOP1 clock in either direction from an external UTC source
 * (NTP). Also supplies UTC to no-fix reports before the first fix; never touches
 * lat/lon/speed/heading/altitude/fix_quality or location acquisition UTC. */
void gps_apply_ntp_utc(uint16_t year, uint8_t month, uint8_t day,
                       uint8_t hour, uint8_t minute, uint8_t second);
const volatile gps_diag_t *gps_get_diag(void);

/* Called from UART4_IRQHandler */
void gps_rx_isr(uint8_t byte);

/* Send CASIC command to GPS module */
void gps_send_cmd(const char *cmd);
int gps_send_raw(const uint8_t *data, uint32_t len);
typedef gps_data_t gps_context_t;

/* True when both coordinates are inside the geographic range. */
static inline bool gps_coord_in_range(const gps_data_t *g)
{
    return g->lat_e7 >= -GPS_LAT_E7_MAX && g->lat_e7 <= GPS_LAT_E7_MAX &&
           g->lon_e7 >= -GPS_LON_E7_MAX && g->lon_e7 <= GPS_LON_E7_MAX;
}

/* Signed longitude difference b-a in 1e-7 deg, wrapped across +/-180. */
static inline int32_t gps_lon_delta_e7(int32_t a, int32_t b)
{
    int64_t d = (int64_t)b - a;
    if (d > GPS_LON_E7_MAX) d -= 2 * (int64_t)GPS_LON_E7_MAX;
    else if (d < -GPS_LON_E7_MAX) d += 2 * (int64_t)GPS_LON_E7_MAX;
    return (int32_t)d;
}

/* Metres per 1e-7 degree of latitude on a 6371 km sphere. */
#define GPS_M_PER_E7  0.0111194926f

/* cos(lat) = sin(pi/2-|lat|), degree-9 Taylor on [0, pi/2].
 * Truncation error <= (pi/2)^11/11! < 3.6e-6; local metre projections only. */
static inline float gps_cos_lat_e7(int32_t lat_e7)
{
    int32_t a = lat_e7 < 0 ? -lat_e7 : lat_e7;
    float x = (float)(GPS_LAT_E7_MAX - a) * 1.745329252e-9f;
    float z = x * x;
    return x + x * z * (-1.0f / 6.0f + z * (1.0f / 120.0f +
           z * (-1.0f / 5040.0f + z * (1.0f / 362880.0f))));
}

#endif
