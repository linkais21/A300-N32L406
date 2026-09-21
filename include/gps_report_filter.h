#ifndef GPS_REPORT_FILTER_H
#define GPS_REPORT_FILTER_H

#include "gps.h"

typedef struct {
    float stop_speed_kmh;       /* 0..10, inclusive stop threshold */
    float move_speed_kmh;       /* >stop, <=30; three distinct RMC fixes */
    uint16_t stable_accel_mg;   /* 1..200, max per-axis window peak-to-peak */
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
    uint8_t state; /* 0 unknown, 1 moving, 2 candidate, 3 locked, 4 suspect */
    uint8_t blockers;
} gps_report_filter_diag_t;

/* Main-loop observation only: no I/O, no evidence/anchor mutation. */
void gps_report_filter_get_diag(gps_report_filter_diag_t *out, uint32_t now_ms);

/* All APIs: main-loop only, not ISR/thread safe; no heap, persistence or waits
 * beyond one bounded existing i2c_accel_read transaction in process().
 * Module owns state; pointers remain caller-owned and are never retained.
 * L406 trial defaults: 1/2 km/h, 120/180 mg, 30 seconds.
 * Independent of VIBSENS (wake/working-mode motion sensitivity).
 * An existing lock ignores <=3 km/h speed when acceleration is stable and
 * quality fix is stale, satellites <6 or HDOP is missing/invalid/>2.5. Good-quality speed and
 * >3 km/h weak speed still release after three distinct RMC samples.
 * New locks require fresh quality (satellites>=6, 0<HDOP<=2.5), <=1 km/h
 * and stable acceleration for 30 seconds; all samples within 8m of the first.
 * A suspect state keeps the anchor while observing >=0.5 km/h creep:
 * 10..60 seconds, >=4m, consistent course/displacement and speed integral.
 * Confirmation releases the anchor and raises a bounded live-report event;
 * candidates are never replayed. Consistent GNSS drift can still mimic motion.
 * reset clears evidence/anchor. Call reset on external wake.
 * Invalid/stale GNSS retains a locked anchor for at most 10 seconds with
 * continuous stable acceleration; copy never substitutes an invalid fix.
 * Disabled GNSS/filter, sensor failure or >1000ms sampling gap clears evidence.
 * Adapted for L406 DA218E signed 12-bit output at 1024 LSB/g. */
void gps_report_filter_init(void);
void gps_report_filter_reset(void);
/* Call regularly after GNSS integrity update; at most one read / 200ms.
 * now_ms is the monotonic uint32 tick, including natural wraparound. */
void gps_report_filter_process(uint32_t now_ms);
/* Main-loop event expires after 15 s; acknowledge only after live send success. */
bool gps_report_filter_motion_pending(uint32_t now_ms);
void gps_report_filter_motion_ack(void);
/* LIVE data selection only: copies raw to out, substitutes lat/lon/speed/course
 * only when locked and evidence is fresh. Returns whether substitution occurred.
 * NULL -> false; raw == out -> false without mutation. Other input stays intact.
 * Never call on stored history/replay: cache the returned live copy at capture
 * time and preserve that historical snapshot on replay. No I/O or state change. */
bool gps_report_filter_copy(const gps_data_t *raw, gps_data_t *out, uint32_t now_ms);

#endif
