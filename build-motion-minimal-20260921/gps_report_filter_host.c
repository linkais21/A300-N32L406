#include "gps_report_filter.h"
#include "flash_config.h"
#include "i2c_accel.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

static gps_data_t raw;
static accel_data_t acceleration;
static device_config_t device;
static bool sensor_ok, trusted, enabled;
static unsigned reads;
static uint32_t now;

const gps_data_t *gps_get_data(void) { return &raw; }
bool gps_is_enabled(void) { return enabled; }
device_config_t *cfg_get(void) { return &device; }
bool gps_is_valid(void) { return trusted && raw.valid; }
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
        before.lat = out.lat; before.lon = out.lon;
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
    raw.lat = 22.755687; raw.lon = 114.42117;
    raw.speed_kmh = 0.3f; raw.heading = 254.0f;
    raw.valid = true; raw.fix_quality = 1; raw.satellites = 15;
    raw.hdop = 0.9f; raw.altitude_m = 25.0f;
    acceleration.x = 0; acceleration.y = 0; acceleration.z = 1024;
    sensor_ok = trusted = enabled = true;
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
        raw.lat += 0.0000004;
        step(i % 5 == 0);
    }
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
        raw.lat += 0.00001; raw.lon -= 0.00001;
        step(true);
        assert(gps_report_filter_copy(&raw, &out, now));
        assert(out.lat == first.lat && out.lon == first.lon);
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
    raw.speed_kmh = 2.0f;
    step(true); assert(locked());
    for (unsigned i = 0; i < 10; i++) { step(false); assert(locked()); }
    step(true); assert(locked());
    step(true); assert(!locked());
    raw.speed_kmh = 0.5f; anchor();
    raw.speed_kmh = 2.0f; step(true); assert(locked());
    raw.speed_kmh = 0.5f; step(true); assert(locked());
    raw.speed_kmh = 2.0f; step(true); assert(locked());
    step(true); assert(locked());
    step(true); assert(!locked());
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
        case 3: raw.lat = NAN; break;
        case 4: raw.lon = 181.0; break;
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
    gps_report_filter_reset(); raw.speed_kmh = 1.01f;
    quiet(40); assert(!locked());
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
    setup(); raw.lat = 50.123456789; raw.lon = -100.987654321;
    for (unsigned i = 0; i < 180; ++i) step(i % 5 == 0);
    gps_data_t out;
    assert(gps_report_filter_copy(&raw, &out, now));
    assert(fabs(out.lat - raw.lat) < 0.0000001);
    assert(fabs(out.lon - raw.lon) < 0.0000001);
    assert(out.lon < 0.0);
    puts("PASS: bounded centimetre coordinate quantization in both hemispheres");
}

static void test_dateline_and_zero_tick(void)
{
    setup();
    for (unsigned i = 0; i < 200; i++) {
        raw.lon = i % 2 == 0 ? 179.99999 : -179.99999;
        step(i % 5 == 0);
    }
    gps_data_t out;
    assert(gps_report_filter_copy(&raw, &out, now));
    assert(fabs(out.lon) > 179.99 && fabs(out.lon) <= 180.0);
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
    gps_report_filter_get_diag(&d, now);
    assert(!locked() && (d.blockers & GPS_REPORT_BLOCK_SPEED));
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
        raw.lat += 0.0000003;
        raw.lon -= 0.0000002;
        step(i % 5u == 0u);
        assert(gps_report_filter_copy(&raw, &out, now));
        assert(out.lat == first.lat && out.lon == first.lon);
        assert(out.speed_kmh == 0.0f);
    }
    /* Unknown quality / few satellites are not independent motion proof. */
    const float hdop[] = {0.0f, NAN, -1.0f, 2.51f, 0.9f};
    for (unsigned q = 0; q < sizeof(hdop)/sizeof(hdop[0]); ++q) {
        raw.hdop = hdop[q]; raw.satellites = q == 4 ? 5 : 9;
        raw.speed_kmh = 3.0f;
        step(true); step(true); step(true); assert(locked());
    }
    /* Better quality restores the original low-speed release path. */
    raw.hdop = 2.5f; raw.satellites = 6; raw.speed_kmh = 2.0f;
    step(true); assert(locked()); step(true); assert(locked());
    step(true); assert(!locked());
    setup(); anchor(); raw.hdop = 4.0f; raw.speed_kmh = 3.01f;
    step(true); step(true); step(true); assert(!locked());
    setup(); anchor(); raw.hdop = 4.0f; raw.speed_kmh = 0.5f;
    acceleration.x = 185; step(true); assert(!locked());
    /* Do not create a new stationary anchor from weak low-speed travel. */
    setup(); raw.hdop = 4.0f; raw.speed_kmh = 2.0f;
    quiet(40); assert(!locked());
    puts("PASS: weak 1-3 km/h drift held; quality, speed and acceleration release");
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
        raw.lat += 0.001; step(true);
        if (failure == 0) {
            assert(gps_report_filter_copy(&raw, &out, now));
            assert(out.lat == first.lat && out.lon == first.lon);
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
        raw.lat += 0.0000001;
        raw.lon -= 0.0000001;
        step(i % 5u == 0u);
        if (i == 175u) {
            assert(gps_report_filter_copy(&raw, &first, now));
        } else if (i > 175u) {
            assert(gps_report_filter_copy(&raw, &out, now));
            assert(first.lat == out.lat && first.lon == out.lon);
        }
    }
    /* With noise continuing, distinct speed evidence must still release. */
    raw.speed_kmh = 2.0f;
    step(true); assert(locked());
    step(true); assert(locked());
    step(true); assert(!locked());
    puts("PASS: ten-minute 100 LSB stationary noise, fixed coordinates, speed release");
}

int main(void)
{
#if defined(A300_CUSTOM_LOW_POWER) || defined(A300_CUSTOM_BALER_COUNTER) || defined(A300_CUSTOM_CMCC_RTK)
    setup(); quiet(40);
    assert(!locked() && reads == 0);
    puts("PASS: custom profile unchanged, no new polling");
#else
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
