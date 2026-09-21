#ifndef GPS_REPORT_FILTER_H
#define GPS_REPORT_FILTER_H

#include "gps.h"

typedef struct {
    float stop_speed_kmh;       /* 0..10, inclusive stop threshold */
    float move_speed_kmh;       /* >stop, <=30; three distinct RMC fixes */
    uint16_t stable_accel_mg;   /* 1..200, max per-axis filtered window peak-to-peak */
    uint16_t move_accel_mg;     /* >stable, <=1000, inclusive release threshold */
    uint32_t stationary_ms;     /* 5000..300000; independent of power idle time */
} gps_report_filter_config_t;

/* Sticky evidence since init/reset; several causes may coexist. */
#define GPS_REPORT_BLOCK_DISABLED  0x01u
#define GPS_REPORT_BLOCK_FIX       0x02u
#define GPS_REPORT_BLOCK_GAP       0x04u
#define GPS_REPORT_BLOCK_SENSOR    0x08u
#define GPS_REPORT_BLOCK_RMC_GAP   0x10u
#define GPS_REPORT_BLOCK_ACCEL     0x20u
#define GPS_REPORT_BLOCK_SPEED     0x40u
#define GPS_REPORT_BLOCK_UNSTABLE  0x80u
typedef struct {
    uint32_t candidate_ms;
    uint16_t span_lsb;
    uint8_t state; /* 0 unknown, 1 moving, 2 candidate, 3 locked */
    uint8_t blockers;
} gps_report_filter_diag_t;

/* Main-loop observation only: no I/O, no evidence/anchor mutation. */
void gps_report_filter_get_diag(gps_report_filter_diag_t *out, uint32_t now_ms);

/* All APIs: main-loop only, not ISR/thread safe; no heap, persistence or waits
 * beyond one bounded existing i2c_accel_read transaction in process().
 * Module owns state; pointers remain caller-owned and are never retained.
 * Fixed reference defaults: 1/2 km/h, 30/60 mg, 30 seconds.
 * Median-of-three and pair averaging reject isolated sensor spikes. Sustained
 * acceleration steps release within 3 new polls (600 ms at nominal cadence).
 * Candidate gray-zone instability pauses quiet evidence for <2000 ms; a
 * longer continuous interval discards it. Invalid raw samples never smooth
 * into valid evidence. reset clears evidence/anchor and smoothing history.
 * Call reset on external wake. Invalid/stale GNSS, disabled GNSS/filter,
 * acceleration read failure or >1000ms sampling gap clears evidence.
 * Adapted for L406 DA218E signed 12-bit output at 1024 LSB/g. */
void gps_report_filter_init(void);
void gps_report_filter_reset(void);
/* Call regularly after GNSS integrity update; at most one read / 200ms.
 * now_ms is the monotonic uint32 tick, including natural wraparound. */
void gps_report_filter_process(uint32_t now_ms);
/* LIVE data selection only: copies raw to out, substitutes lat/lon/speed/course
 * only when locked and evidence is fresh. Returns whether substitution occurred.
 * NULL -> false; raw == out -> false without mutation. Other input stays intact.
 * Never call on stored history/replay: cache the returned live copy at capture
 * time and preserve that historical snapshot on replay. No I/O or state change. */
bool gps_report_filter_copy(const gps_data_t *raw, gps_data_t *out, uint32_t now_ms);

#endif
