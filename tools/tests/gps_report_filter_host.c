#include "gps_report_filter.h"
#include "flash_config.h"
#include "i2c_accel.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static gps_data_t raw;
static accel_data_t acceleration;
static device_config_t device;
static bool sensor_ok, trusted, enabled, gga_fresh;
static unsigned reads;
static uint32_t now;
/* Sub-e7 residuals so slow host-modelled motion is not lost to rounding. */
static double frac_lat, frac_lon;

static void move_e7(double dlat_e7, double dlon_e7)
{
    double a = dlat_e7 + frac_lat, b = dlon_e7 + frac_lon;
    long long ia = llround(a), ib = llround(b);
    long long lon = (long long)raw.lon_e7 + ib;
    frac_lat = a - (double)ia; frac_lon = b - (double)ib;
    raw.lat_e7 += (int32_t)ia;
    if (lon > GPS_LON_E7_MAX) lon -= 2LL * GPS_LON_E7_MAX;
    if (lon < -GPS_LON_E7_MAX) lon += 2LL * GPS_LON_E7_MAX;
    raw.lon_e7 = (int32_t)lon;
}

const gps_data_t *gps_get_data(void) { return &raw; }
bool gps_is_enabled(void) { return enabled; }
device_config_t *cfg_get(void) { return &device; }
bool gps_is_valid(void) { return trusted && raw.valid; }
bool gps_quality_fix_fresh(void) { return gga_fresh && gps_is_valid() && raw.fix_quality != 0u; }
/* GSV CN0 average; 0 means no complete recent GSV cycle. */
static uint8_t cn0_avg;
bool gps_get_quality(gps_quality_t *out) { memset(out, 0, sizeof *out); if (!cn0_avg) return false; out->satellites = raw.satellites; out->average = cn0_avg; return true; }
bool i2c_accel_read(accel_data_t *out)
{
    reads++;
    if (!sensor_ok) return false;
    *out = acceleration;
    return true;
}

static bool locked(void)
{
    gps_data_t out;
    gps_data_t before = raw;
    bool result = gps_report_filter_copy(&raw, &out, now);
    assert(memcmp(&raw, &before, sizeof(raw)) == 0);
    if (result) {
        assert(out.speed_kmh == 0.0f && out.heading == 0.0f);
        before.lat_e7 = out.lat_e7; before.lon_e7 = out.lon_e7;
        before.speed_kmh = 0.0f; before.heading = 0.0f;
        assert(memcmp(&out, &before, sizeof(out)) == 0);
    } else {
        assert(memcmp(&out, &raw, sizeof(out)) == 0);
    }
    return result;
}

static void setup(void)
{
    memset(&raw, 0, sizeof(raw));
    memset(&device, 0, sizeof(device));
    raw.lat_e7 = 227556870; raw.lon_e7 = 1144211700;
    frac_lat = frac_lon = 0.0;
    raw.speed_kmh = 0.3f; raw.heading = 254.0f;
    raw.valid = true; raw.fix_quality = 1; raw.satellites = 15;
    raw.hdop = 0.9f; raw.altitude_m = 25.0f;
    acceleration.x = 0; acceleration.y = 0; acceleration.z = 1024;
    sensor_ok = trusted = enabled = true;
    gga_fresh = true;
    cn0_avg = 0;
    device.stopdrift_en = 1; device.stopdrift_thr = 50;
    reads = 0; now = 10000;
    gps_report_filter_init();
}

static void step(bool new_rmc)
{
    now += 200;
    if (new_rmc) raw.heading_update_ms = now;
    raw.last_update_ms = now;
    gps_report_filter_process(now);
}

static void quiet(unsigned seconds)
{
    for (unsigned i = 0; i < seconds * 5; i++) {
        /* True fixes drift slowly by >5 m across the candidate window. */
        raw.lat_e7 += 4;
        step(i % 5 == 0);
    }
}

static void travel(float speed, float heading)
{
    double angle = heading * 0.0174532925199433;
    double metres = speed / 3.6 * 0.2;
    double dlat = metres*cos(angle)/111319.5*1e7;
    double lat = (raw.lat_e7 + dlat) * 1e-7;
    move_e7(dlat, metres*sin(angle)/(111319.5*cos(lat*0.0174532925199433))*1e7);
}

/* Real driving: displacement agrees with SOG and course. Returns the step at
 * which the anchor released, or 0 if it held for the whole budget. */
static unsigned drive_until_release(float speed, float heading, unsigned budget)
{
    raw.speed_kmh = speed; raw.heading = heading;
    for (unsigned i = 0; i < budget; ++i) {
        travel(speed, heading); step(i % 5u == 0u);
        if (!locked()) return i + 1u;
    }
    return 0u;
}

#if !defined(A300_CUSTOM_LOW_POWER) && !defined(A300_CUSTOM_BALER_COUNTER) && !defined(A300_CUSTOM_CMCC_RTK)
static void anchor(void)
{
    quiet(35);
    assert(locked());
}

static void test_acc_on_drift_and_immutable_raw(void)
{
    setup();
    quiet(30);
    assert(!locked());
    quiet(5);
    assert(locked());
    gps_data_t first, out;
    assert(gps_report_filter_copy(&raw, &first, now));
    for (unsigned i = 0; i < 100; i++) {
        raw.lat_e7 += 100; raw.lon_e7 -= 100;
        step(true);
        assert(gps_report_filter_copy(&raw, &out, now));
        assert(out.lat_e7 == first.lat_e7 && out.lon_e7 == first.lon_e7);
    }
    assert(!gps_report_filter_copy(NULL, &out, now));
    assert(!gps_report_filter_copy(&raw, NULL, now));
    gps_data_t historical = raw;
    now += 4000;
    assert(!gps_report_filter_copy(&historical, &out, now));
    assert(memcmp(&historical, &out, sizeof(out)) == 0);
    puts("PASS: ACC-independent timed anchor, >100m drift, raw/quality/time preserved");
}

static void test_motion_and_duplicate_rmc(void)
{
    setup(); anchor();
    /* G452 rule: with a quiet sensor, receiver speed without displacement is
     * parked multipath, however many distinct RMC fixes repeat it. */
    raw.speed_kmh = 8.0f;
    for (unsigned i = 0; i < 300; i++) { step(i % 5u == 0u); assert(locked()); }
    raw.speed_kmh = 0.0f;
    /* Repeated RMC timestamps cannot add trajectory evidence: a stale stream
     * drops the anchor as invalid, never as confirmed motion. */
    raw.speed_kmh = 10.0f; raw.heading = 90.0f;
    for (unsigned i = 0; i < 300; i++) { travel(10.0f, 90.0f); step(false); }
    assert(!gps_report_filter_motion_pending(now));
    /* Genuine driving releases on a coherent trajectory. */
    raw.speed_kmh = 0.5f; anchor();
    assert(drive_until_release(10.0f, 90.0f, 500u) != 0u);
    raw.speed_kmh = 0.5f; anchor();
    acceleration.x = 185; step(true); assert(!locked());
    /* Slow movement must not be zeroed solely because speed is low. */
    assert(raw.speed_kmh == 0.5f);
    gps_report_filter_reset();
    raw.speed_kmh = 30.0f;
    quiet(40); assert(!locked());
    puts("PASS: distinct RMC confirmation, fast accel unlock, genuine creep/driving");
}

static void test_failures_and_recovery(void)
{
    for (unsigned failure = 0; failure < 9; failure++) {
        setup(); anchor();
        switch (failure) {
        case 0: sensor_ok = false; break;
        case 1: trusted = false; break;
        case 2: raw.valid = false; break;
        case 3: raw.lat_e7 = 910000000; break; /* 91 deg */
        case 4: raw.lon_e7 = 1810000000; break; /* 181 deg */
        case 5: raw.speed_kmh = NAN; break;
        case 6: raw.speed_kmh = -1.0f; break;
        case 7: enabled = false; break;
        default: device.stopdrift_en = 0; break;
        }
        step(true); assert(!locked());
    }
    setup(); anchor();
    now += 1001; step(true); assert(!locked());
    anchor();
    for (unsigned i = 0; i < 20; i++) step(false);
    assert(!locked());
    anchor(); gps_report_filter_reset(); assert(!locked());
    anchor(); gps_report_filter_init(); assert(!locked());
    setup(); anchor(); sensor_ok = false; step(true);
    unsigned failed_reads = reads;
    for (unsigned i = 0; i < 500; i++) gps_report_filter_process(now);
    assert(reads == failed_reads && !locked());
    sensor_ok = true; anchor();
    acceleration.x = acceleration.y = acceleration.z = 0;
    step(true); assert(!locked());
    acceleration.z = 1024; anchor();
    acceleration.x = 2047; step(true); assert(!locked());
    puts("PASS: invalid/stale/failed sensor, gaps, wake and repeated reboot recovery");
}

static void test_stability_boundaries_and_polling(void)
{
    setup();
    for (unsigned i = 0; i < 200; i++) {
        acceleration.x = (i % 2 == 0) ? 0 : 123; /* 120.12 mg >120mg */
        step(i % 5 == 0);
    }
    assert(!locked());
    setup();
    raw.speed_kmh = 1.0f;
    for (unsigned i = 0; i < 200; i++) {
        acceleration.x = (i % 2 == 0) ? 0 : 122;
        step(i % 5 == 0);
    }
    assert(locked());
    /* Window gray area preserves existing anchor but prevents new one. */
    acceleration.x = 184; step(true); assert(locked());
    acceleration.x = 185; step(true); assert(!locked());
    /* Above the strong stop speed the 20 m weak cluster decides (G452):
     * reported speed with a quiet sensor and no travel is parked drift. */
    gps_report_filter_reset(); raw.speed_kmh = 1.01f;
    quiet(40); assert(locked());
    gps_report_filter_reset(); raw.speed_kmh = 30.01f;
    quiet(40); assert(!locked()); /* beyond any parked-multipath speed */
    setup();
    step(true);
    unsigned previous = reads;
    for (unsigned i = 0; i < 500; i++) gps_report_filter_process(now);
    assert(reads == previous && !locked());
    /* A GGA/GSV stream without new RMC cannot accumulate 5 fixes. */
    for (unsigned i = 0; i < 200; i++) step(false);
    assert(!locked());
    puts("PASS: acceleration/speed boundaries, bounded reads, no duplicate evidence");
}

static void test_configuration_and_wrap(void)
{
    setup();
    now = UINT32_MAX - 2000;
    quiet(35); assert(locked());
    gps_report_filter_reset(); assert(!locked());
    puts("PASS: fixed reference defaults, reset and tick wrap");
}

static void test_coordinate_quantization(void)
{
    setup(); raw.lat_e7 = 501234568; raw.lon_e7 = -1009876543;
    for (unsigned i = 0; i < 180; ++i) step(i % 5 == 0);
    gps_data_t out;
    assert(gps_report_filter_copy(&raw, &out, now));
    /* Identical integer samples: the anchor is exact, no quantization. */
    assert(out.lat_e7 == raw.lat_e7 && out.lon_e7 == raw.lon_e7);
    assert(out.lon_e7 < 0);
    /* Non-integer mean in the southern/western hemisphere rounds to nearest. */
    setup(); raw.lat_e7 = -501234568; raw.lon_e7 = -1009876543;
    for (unsigned i = 0; i < 180; ++i) {
        raw.lat_e7 = -501234568 - (int32_t)(i % 2u);
        raw.lon_e7 = -1009876543 - (int32_t)(i % 2u);
        step(i % 5 == 0);
    }
    assert(gps_report_filter_copy(&raw, &out, now));
    assert(out.lat_e7 <= -501234568 && out.lat_e7 >= -501234569);
    assert(out.lon_e7 <= -1009876543 && out.lon_e7 >= -1009876544);
    puts("PASS: bounded centimetre coordinate quantization in both hemispheres");
}

static void test_dateline_and_zero_tick(void)
{
    setup();
    for (unsigned i = 0; i < 200; i++) {
        raw.lon_e7 = i % 2 == 0 ? 1799999900 : -1799999900;
        step(i % 5 == 0);
    }
    gps_data_t out;
    assert(gps_report_filter_copy(&raw, &out, now));
    assert(llabs((long long)out.lon_e7) > 1799900000LL &&
           llabs((long long)out.lon_e7) <= GPS_LON_E7_MAX);
    setup();
    now = UINT32_MAX - 199u;
    step(true); assert(now == 0u);
    quiet(35); assert(locked());
    /* A caller cannot accidentally filter the receiver object in place. */
    gps_data_t before = raw;
    assert(!gps_report_filter_copy(&raw, &raw, now));
    assert(memcmp(&raw, &before, sizeof(raw)) == 0);
    puts("PASS: dateline circular longitude, zero-valued wrap tick, no in-place mutation");
}
static void test_diagnostics(void)
{
    gps_report_filter_diag_t d;
    setup();
    quiet(35);
    unsigned previous = reads;
    gps_report_filter_get_diag(&d, now);
    assert(d.state == 3u && d.blockers == 0u);
    assert(reads == previous && locked());
    /* Quiet speed alone cannot establish an anchor with a noisy sensor. */
    setup(); raw.speed_kmh = 0.0f;
    for (unsigned i = 0; i < 200; ++i) {
        acceleration.z = i % 2u ? 1000 : 1123;
        step(i % 5u == 0u);
    }
    gps_report_filter_get_diag(&d, now);
    assert(!locked() && d.span_lsb == 123u);
    assert(d.blockers & GPS_REPORT_BLOCK_UNSTABLE);
    setup(); quiet(35);
    acceleration.x = 185; step(true);
    gps_report_filter_get_diag(&d, now);
    assert(!locked() && (d.blockers & GPS_REPORT_BLOCK_ACCEL));
    setup(); quiet(35); now += 1200; step(true);
    gps_report_filter_get_diag(&d, now);
    assert(!locked() && (d.blockers & GPS_REPORT_BLOCK_GAP));
    setup(); sensor_ok = false; step(true);
    gps_report_filter_get_diag(&d, now);
    assert(d.blockers & GPS_REPORT_BLOCK_SENSOR);
    setup(); raw.valid = false; step(true);
    gps_report_filter_get_diag(&d, now);
    assert(d.blockers & GPS_REPORT_BLOCK_FIX);
    setup(); device.stopdrift_en = 0; step(true);
    gps_report_filter_get_diag(&d, now);
    assert(d.blockers & GPS_REPORT_BLOCK_DISABLED);
    setup(); quiet(35); raw.speed_kmh = 2.0f;
    step(true); step(true); step(true);
    assert(locked()); /* quiet anchor ignores speed-only evidence */
    gps_report_filter_reset();
    gps_report_filter_get_diag(&d, now);
    assert(d.state == 0u && d.blockers == 0u && d.span_lsb == 0u);
    gps_report_filter_get_diag(NULL, now);
    puts("PASS: diagnostic causes, noisy zero-speed input, read-only observation and reset");
}

static void test_weak_signal_stationary(void)
{
    setup(); anchor();
    gps_data_t first, out;
    assert(gps_report_filter_copy(&raw, &first, now));
    raw.hdop = 4.0f;
    for (unsigned i = 0; i < 3000; ++i) {
        raw.speed_kmh = i < 100u ? 2.5f : 1.0f + (float)(i % 3u);
        raw.lat_e7 += 3;
        raw.lon_e7 -= 2;
        step(i % 5u == 0u);
        assert(gps_report_filter_copy(&raw, &out, now));
        assert(out.lat_e7 == first.lat_e7 && out.lon_e7 == first.lon_e7);
        assert(out.speed_kmh == 0.0f);
    }
    /* Unknown quality / few satellites are not independent motion proof. */
    const float hdop[] = {0.0f, NAN, -1.0f, 2.51f, 0.9f};
    for (unsigned q = 0; q < sizeof(hdop)/sizeof(hdop[0]); ++q) {
        raw.hdop = hdop[q]; raw.satellites = q == 4 ? 5 : 9;
        raw.speed_kmh = 3.0f;
        step(true); step(true); step(true); assert(locked());
    }
    /* Good quality speed without displacement still holds while quiet. */
    raw.hdop = 2.5f; raw.satellites = 6; raw.speed_kmh = 2.0f;
    step(true); step(true); step(true); assert(locked());
    setup(); anchor(); raw.hdop = 4.0f; raw.speed_kmh = 3.01f;
    step(true); step(true); step(true); assert(locked());
    /* A real path still releases in weak conditions. */
    setup(); anchor(); raw.hdop = 4.0f;
    assert(drive_until_release(8.0f, 0.0f, 600u) != 0u);
    setup(); anchor(); raw.hdop = 4.0f; raw.speed_kmh = 0.5f;
    acceleration.x = 185; step(true); assert(!locked());
    /* G452 rule: a weak fix with a quiet sensor and a concentrated cluster
     * is parked, whatever speed the receiver reports. */
    setup(); raw.hdop = 4.0f; raw.speed_kmh = 2.0f;
    quiet(40); assert(locked());
    /* Real weak-signal travel leaves the 20 m cluster and never locks. */
    setup(); raw.hdop = 4.0f; raw.speed_kmh = 5.0f; raw.heading = 0.0f;
    for (unsigned i = 0; i < 1500; ++i) { travel(5.0f, 0.0f); step(i % 5u == 0u); assert(!locked()); }
    puts("PASS: weak 1-3 km/h drift held; quality, speed and acceleration release");
}

static void test_anchor_quality_and_cluster(void)
{
    /* Weak quality with a quiet sensor and tight cluster now locks (G452). */
    setup(); raw.hdop = 4.0f; quiet(40); assert(locked());
    setup(); raw.satellites = 5; quiet(40); assert(locked());
    /* Below the receiver-solution floor it still never locks. */
    setup(); raw.satellites = 3; quiet(40); assert(!locked());
    setup(); raw.hdop = NAN; quiet(40); assert(!locked());
    setup(); raw.fix_quality = 0; quiet(40); assert(!locked());
    /* Stale GGA quality is weak, not invalid: a quiet cluster still locks. */
    setup(); gga_fresh = false; quiet(40); assert(locked());
    setup();
    for (unsigned i=0;i<200;++i) {
        raw.lat_e7 = 100000000 + (i%10 < 5 ? 0 : 10000);
        step(i%5==0);
        assert(!locked());
    }
    raw.lat_e7=100000000; quiet(35); assert(locked());
    puts("PASS: new anchor requires quality and concentrated observations");
}

static void test_smooth_creep(void)
{
    setup(); anchor(); raw.hdop=4.0f; raw.speed_kmh=1.0f; raw.heading=0.0f;
    unsigned released=0;
    for(unsigned i=0;i<200;++i) {
        move_e7((1.0/3.6)*0.2/111319.5*1e7, 0.0);
        step(i%5==0);
        if(!locked()) { released=i+1;break; }
    }
    assert(released>=50 && released<200);
    puts("PASS: smooth weak-signal creep releases without vibration");
}



static void test_creep_geography_and_events(void)
{
    const float speeds[] = {0.5f,1.0f,2.5f};
    const int32_t latitudes[] = {0,500000000,-800000000,890000000};
    for(unsigned v=0;v<3;v++) for(unsigned l=0;l<4;l++)
    for(unsigned dir=0;dir<8;dir++) {
        setup(); raw.lat_e7=latitudes[l]; raw.lon_e7=1799999900;
        /* Let both candidate and confirmed motion cross uint32 wrap. */
        now=UINT32_MAX-55000u;
        for(unsigned i=0;i<180;i++) step(i%5==0);
        assert(locked());
        raw.hdop=4.0f; raw.speed_kmh=speeds[v]; raw.heading=dir*45.0f;
        unsigned i;
        for(i=0;i<250;i++) {
            travel(raw.speed_kmh,raw.heading);step(i%5==0);
            if(!locked()) break;
        }
        assert(i>=50 && i<250);
        assert(gps_report_filter_motion_pending(now));
        assert(gps_report_filter_motion_pending(now+15000));
        assert(!gps_report_filter_motion_pending(now+15001));
    }
    setup();anchor();
    assert(drive_until_release(10.0f,90.0f,500u)!=0u);
    assert(gps_report_filter_motion_pending(now));
    gps_report_filter_motion_ack();assert(!gps_report_filter_motion_pending(now));
    puts("PASS: 96 creep scenarios, 8 headings, equator/high latitude/dateline/tick wrap, event expiry/ack");
}

static void test_suspect_rejection(void)
{
    for(unsigned mode=0;mode<8;mode++) {
        setup();anchor();raw.hdop=4.0f;raw.speed_kmh=1.0f;raw.heading=0;
        int32_t lat=raw.lat_e7;
        for(unsigned i=0;i<350;i++) {
            switch(mode) {
            case 0: raw.lat_e7=lat+10000;break; /* one jump, then still */
            case 1: raw.lat_e7=lat+(i%10<5?500:0);break; /* alternating */
            case 2: travel(1,90);break; /* displacement disagrees with heading */
            case 3: travel(1,0);raw.speed_kmh=0;break;
            case 4: travel(1,0);raw.heading=NAN;break;
            case 5: travel(1,0);raw.heading=i%10<5?0:90;break;
            case 6: travel(0.05f,0);break; /* displacement too small for speed */
            default: break; /* speed but no displacement, suspect times out */
            }
            step(i%5==0);assert(locked());
            assert(!gps_report_filter_motion_pending(now));
        }
    }
    /* Loss/reset/gray acceleration cannot retain half-built movement evidence. */
    for(unsigned failure=0;failure<5;failure++) {
        setup();anchor();raw.hdop=4;raw.speed_kmh=1;raw.heading=0;
        for(unsigned i=0;i<45;i++) {travel(1,0);step(i%5==0);}
        switch(failure) {
        case 0: raw.valid=false;break;
        case 1: sensor_ok=false;break;
        case 2: acceleration.x=123;break;
        case 3: gps_report_filter_reset();break;
        default: for(unsigned i=0;i<20;i++) step(false);break;
        }
        step(true);
        assert(!gps_report_filter_motion_pending(now));
        raw.valid=sensor_ok=true;acceleration.x=0;
        for(unsigned i=0;i<35;i++) {travel(1,0);step(i%5==0);}
        assert(!gps_report_filter_motion_pending(now));
    }
    puts("PASS: jump/zigzag/heading/speed/timeout rejection; incomplete evidence canceled");
}

static void test_short_fix_loss(void)
{
    for (unsigned failure = 0; failure < 5; ++failure) {
        setup(); anchor();
        gps_data_t first, out;
        assert(gps_report_filter_copy(&raw, &first, now));
        raw.valid = false;
        for (unsigned i = 0; i < 25; ++i) {
            if (failure == 1) acceleration.x = i % 2u ? 185 : 0;
            if (failure == 2) sensor_ok = false;
            if (failure == 3 && i == 10) now += 1001;
            if (failure == 4 && i == 10) gps_report_filter_reset();
            step(true); assert(!locked()); /* never manufacture a valid fix */
        }
        sensor_ok = true; acceleration.x = 0;
        raw.valid = true; raw.hdop = 4.0f; raw.speed_kmh = 2.5f;
        raw.lat_e7 += 10000; step(true);
        if (failure == 0) {
            assert(gps_report_filter_copy(&raw, &out, now));
            assert(out.lat_e7 == first.lat_e7 && out.lon_e7 == first.lon_e7);
        } else assert(!locked());
    }
    setup(); anchor(); raw.valid = false;
    for (unsigned i = 0; i < 51; ++i) step(true);
    raw.valid = true; step(true); assert(!locked());
    /* Recovery just after the retention deadline must not revive the anchor. */
    setup(); anchor(); raw.valid = false;
    for (unsigned i = 0; i < 50; ++i) step(true);
    raw.valid = true; step(true); assert(!locked());
    setup(); anchor();
    for (unsigned i = 0; i < 25; ++i) step(false);
    assert(!locked()); /* fresh GGA alone cannot make a live RMC */
    step(true); assert(locked());
    setup(); anchor(); raw.valid = false;
    acceleration.x = 123; step(true);
    raw.valid = true; step(true); assert(!locked());
    setup(); now = UINT32_MAX - 40000u; anchor();
    raw.valid = false;
    for (unsigned i = 0; i < 30; ++i) step(true);
    raw.valid = true; step(true); assert(locked());
    puts("PASS: bounded fix-loss hold, invalid output, motion/sensor/gap/reset and wrap");
}
#endif

/* Constructed 200 ms input covering the observed 100 LSB diagnostic span.
 * The field log samples windows every 30 s, so this is not a raw log replay. */
static void test_stationary_sensor_noise(void)
{
    setup(); raw.speed_kmh = 0.0f;
    gps_data_t first, out;
    for (unsigned i = 0; i < 3000; ++i) {
        acceleration.z = (i % 2u) ? 974 : 1074;
        raw.lat_e7 += 1;
        raw.lon_e7 -= 1;
        step(i % 5u == 0u);
        if (i == 175u) {
            assert(gps_report_filter_copy(&raw, &first, now));
        } else if (i > 175u) {
            assert(gps_report_filter_copy(&raw, &out, now));
            assert(first.lat_e7 == out.lat_e7 && first.lon_e7 == out.lon_e7);
        }
    }
    /* With noise continuing, speed alone holds; a real path releases. */
    raw.speed_kmh = 2.0f;
    step(true); step(true); step(true); assert(locked());
    assert(drive_until_release(10.0f, 45.0f, 500u) != 0u);
    puts("PASS: ten-minute 100 LSB stationary noise, fixed coordinates, trajectory release");
}


/* Field capture 2026-10-24 (V3.096, ACC on, parked, weak signal): 26 receiver
 * fixes 5-12 s apart, 8-12 satellites, HDOP 0.9, receiver SOG 0..10.1 km/h,
 * raw position wandering 5..52 m around the parked point, Gsensor span
 * 15..63 LSB. Offsets are e7 relative to the first fix. A parked vehicle must
 * report one frozen point with zero speed after the initial lock. */
static const struct { float speed; int32_t dlat, dlon; uint8_t sats; } weak_field[] = {
 {0.0f,0,0,17},{2.6f,-67,433,11},{3.0f,-715,2332,12},{2.3f,-923,2669,11},{2.8f,-1172,1079,11},
 {0.5f,-2587,967,10},{10.1f,-3970,927,10},{0.4f,-4304,1643,11},{3.2f,-4199,1670,12},
 {4.7f,-855,1265,12},{2.8f,-1713,1719,11},{0.4f,-893,1124,12},{4.9f,-1005,2720,11},
 {5.8f,-1532,3160,10},{2.2f,-2332,2478,11},{3.2f,-3769,1796,11},{0.8f,-3052,1397,12},
 {3.5f,-1814,1409,11},{0.0f,-3084,2593,12},{1.4f,-2900,2657,12},{0.0f,-2109,2373,10},
 {1.4f,-2352,2746,8},{1.9f,-291,2486,10},{0.8f,1065,1436,11},{1.8f,948,1818,10},
 {0.6f,369,1498,10}};

static void test_field_weak_signal_parked(void)
{
    setup();
    const int32_t lat0 = raw.lat_e7, lon0 = raw.lon_e7;
    raw.satellites = 17; raw.hdop = 0.9f; raw.speed_kmh = 0.0f;
    anchor();
    gps_data_t first, out;
    assert(gps_report_filter_copy(&raw, &first, now));
    unsigned leaked = 0u;
    /* Replay the capture three times (~13 min), 1 Hz RMC between captured
     * points with the receiver repeating the last reported fix. */
    for (unsigned round = 0u; round < 3u; ++round)
    for (unsigned k = 0u; k < sizeof weak_field / sizeof weak_field[0]; ++k) {
        raw.lat_e7 = lat0 + weak_field[k].dlat;
        raw.lon_e7 = lon0 + weak_field[k].dlon;
        raw.speed_kmh = weak_field[k].speed;
        raw.satellites = weak_field[k].sats;
        raw.heading = (float)((k * 47u) % 360u);
        for (unsigned i = 0u; i < 50u; ++i) {   /* 10 s per captured point */
            acceleration.x = (int16_t)((i * 7u) % 40u); /* span <=63 LSB */
            step(i % 5u == 0u);
            if (!gps_report_filter_copy(&raw, &out, now) ||
                out.lat_e7 != first.lat_e7 || out.lon_e7 != first.lon_e7 ||
                out.speed_kmh != 0.0f) ++leaked;
        }
    }
    if (leaked) fprintf(stderr, "field replay: %u of %u reports leaked drift\n", leaked,
                        3u * 50u * (unsigned)(sizeof weak_field / sizeof weak_field[0]));
    assert(leaked == 0u);
    puts("PASS: field weak-signal parked drift replay held one point");
}


/* Field capture 2026-10-24 16:19 (V3.096): parked, user shook the unit, then
 * left it still. 8-12 satellites, CN0 avg 14-15, receiver SOG 0.3..13.3 km/h,
 * raw fixes wander up to 62 m. After shaking stops the filter must relock and
 * hold one point, and the course must not be trusted (corner reports). */
static const struct { float speed; int32_t dlat, dlon; uint8_t sats; } shake_field[] = {
 {10.1f,0,0,7},{2.9f,540,-900,10},{6.3f,2259,-835,10},{6.1f,3116,-817,12},
 {2.2f,2643,-2510,12},{1.9f,3515,-2573,11},{0.8f,4551,-3256,11},{8.9f,4381,-2183,11},
 {13.3f,3370,-1753,11},{7.1f,2167,-1393,11},{1.9f,2485,-660,11},{5.2f,5185,2286,11},
 {4.9f,4783,960,9},{2.4f,4668,436,9},{0.3f,3835,1325,11},{10.5f,4070,172,11},
 {3.8f,990,1253,11},{5.8f,842,1532,11},{3.8f,1170,3686,10},{4.8f,1909,3200,10},
 {2.3f,2373,5027,9}};

static void test_field_shake_then_park(void)
{
    setup(); raw.hdop = 1.1f; raw.satellites = 11; gga_fresh = false; anchor();
    for (unsigned i = 0u; i < 50u; ++i) { acceleration.x = (i % 2u) ? 300 : 0; step(i % 5u == 0u); }
    assert(!locked());
    const int32_t lat0 = raw.lat_e7, lon0 = raw.lon_e7;
    const unsigned n = sizeof shake_field / sizeof shake_field[0];
    unsigned total = 0u, first = 0u, leaked = 0u, moved = 0u, trusted_course = 0u;
    int32_t alat = 0, alon = 0;
    gps_data_t out;
    for (unsigned k = 0u; k + 1u < n; ++k)
    for (unsigned j = 0u; j < 150u; ++j) {           /* 30 s between captures */
        double f = j / 150.0;
        raw.lat_e7 = lat0 + (int32_t)(shake_field[k].dlat + (shake_field[k+1].dlat - shake_field[k].dlat) * f);
        raw.lon_e7 = lon0 + (int32_t)(shake_field[k].dlon + (shake_field[k+1].dlon - shake_field[k].dlon) * f);
        raw.speed_kmh = shake_field[k].speed; raw.satellites = shake_field[k].sats;
        raw.heading = (float)((k * 97u + j * 13u) % 360u);
        acceleration.x = (int16_t)((j * 7u) % 40u);
        step(j % 5u == 0u); ++total;
        if (total > 5u && gps_report_filter_heading_trusted()) ++trusted_course;
        if (gps_report_filter_copy(&raw, &out, now)) {
            if (!first) { first = total; alat = out.lat_e7; alon = out.lon_e7; }
            else if (out.lat_e7 != alat || out.lon_e7 != alon) ++moved;
        } else if (first) ++leaked;
    }
    if (!first || first > 200u || leaked || moved || trusted_course)
        fprintf(stderr, "shake replay: relock=%.1fs leaked=%u moved=%u trusted_course=%u\n",
                first * 0.2, leaked, moved, trusted_course);
    assert(first != 0u && first <= 200u);  /* relock within 40 s of stillness */
    assert(leaked == 0u && moved == 0u);
    assert(trusted_course == 0u);          /* no corner reports while parked */
    puts("PASS: field shake-then-park replay relocked and held one point");
}

int main(void)
{
#if defined(A300_CUSTOM_LOW_POWER) || defined(A300_CUSTOM_BALER_COUNTER) || defined(A300_CUSTOM_CMCC_RTK)
    setup(); quiet(40);
    assert(!locked() && reads == 0);
    puts("PASS: custom profile unchanged, no new polling");
#else
    test_field_weak_signal_parked();
    test_field_shake_then_park();
    test_anchor_quality_and_cluster();
    test_smooth_creep();
    test_creep_geography_and_events();
    test_suspect_rejection();
    test_weak_signal_stationary();
    test_short_fix_loss();
    test_stationary_sensor_noise();
    test_acc_on_drift_and_immutable_raw();
    test_motion_and_duplicate_rmc();
    test_failures_and_recovery();
    test_stability_boundaries_and_polling();
    test_configuration_and_wrap();
    test_dateline_and_zero_tick();
    test_coordinate_quantization();
    test_diagnostics();
#endif
    return 0;
}
