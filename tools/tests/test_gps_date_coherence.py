"""Real parser regression: GGA cannot refresh an old RMC date."""
import sys
import test_gps_ntp_apply as base

CASES = r'''
int main(void) {
    gps_data_t out;
    gps_init();
    feed_sentence("GPRMC,235959,A,4900.000,N,01200.000,E,1.0,90.0,201026,,,A");
    gps_process();
    feed_sentence("GPGGA,235959,4900.000,N,01200.000,E,1,08,0.9,20.0,M,0.0,M,,");
    gps_process();
    assert(gps_is_valid());
    assert(gps_get_last_trusted(&out) && out.day == 20);
    g_tick_ms += 1000;
    feed_sentence("GPGGA,000000,4901.000,N,01200.000,E,1,08,0.9,20.0,M,0.0,M,,");
    gps_process();
    assert(!gps_is_valid()); /* never yesterday + new midnight position */
    assert(gps_get_last_trusted(&out) && out.day == 21 && out.hour == 0);
    assert(out.lat_e7 == 490000000); /* no new position certified by old RMC */
    feed_sentence("GPRMC,000000,A,4901.000,N,01200.000,E,1.0,90.0,211026,,,A");
    gps_process();
    feed_sentence("GPGGA,000000,4901.000,N,01200.000,E,1,08,0.9,20.0,M,0.0,M,,");
    gps_process();
    assert(gps_is_valid() && gps_get_last_trusted(&out) && out.day == 21);
    g_tick_ms += 4000;
    feed_sentence("GPGGA,000001,4902.000,N,01200.000,E,1,08,0.9,20.0,M,0.0,M,,");
    gps_process();
    assert(!gps_is_valid()); /* GGA alone cannot refresh expired RMC */
    gps_init();
    feed_sentence("GPGGA,080059,4900.000,N,01200.000,E,1,08,0.9,20.0,M,0.0,M,,");
    gps_process();
    assert(!gps_is_valid()); /* GGA has no calendar date */
    feed_sentence("GPRMC,080059,A,4900.000,N,01200.000,E,1.0,90.0,311126,,,A");
    gps_process();
    assert(!gps_is_valid()); /* November 31 is never a date */
    g_tick_ms = UINT32_MAX - 500U;
    feed_sentence("GPRMC,080059,A,4900.000,N,01200.000,E,1.0,90.0,211026,,,A");
    gps_process();
    g_tick_ms += 1000;
    feed_sentence("GPGGA,080100,4900.000,N,01200.000,E,1,08,0.9,20.0,M,0.0,M,,");
    gps_process();
    assert(gps_is_valid() && gps_get_data()->day == 21);
    return 0;
}
'''
base.HARNESS = base.HARNESS.split('int main(void){')[0] + CASES
if __name__ == "__main__":
    raise SystemExit(base.main())
