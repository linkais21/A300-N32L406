"""Exercise the production retained clock while GNSS is unavailable."""
import test_gps_ntp_apply as base

CASES = r'''
    /* Active/no-fix time must advance, including subsecond reads. */
    gps_apply_ntp_utc(2026, 9, 20, 5, 47, 52);
    for (unsigned i=0; i<150; ++i) {
        g_tick_ms += 200;
        gps_process();
        assert(gps_get_last_trusted(&out));
    }
    assert(out.hour==5 && out.minute==48 && out.second==22);
    assert(out.lat==10.0 && out.lon==20.0);
    assert(!gps_is_valid());
    /* Repeated reports and GPS on/off do not restart or double the clock. */
    assert(gps_get_last_trusted(&out) && out.second==22);
    gps_enable(false);
    g_tick_ms += 10000;
    assert(gps_get_last_trusted(&out) && out.second==32);
    gps_enable(true);
    g_tick_ms += 9900; /* enable(true) spent 100 ms awake */
    assert(gps_get_last_trusted(&out) && out.second==42);
    /* STOP1: SysTick freezes, RTC adds just the stopped interval. */
    g_tick_ms += 500;
    gps_advance_last_trusted_seconds(15);
    g_tick_ms += 500;
    assert(gps_get_last_trusted(&out) && out.second==58);
    /* Unsigned tick wrap and leap-day rollover. */
    g_tick_ms = UINT32_MAX-499U;
    gps_apply_ntp_utc(2024, 2, 28, 23, 59, 59);
    g_tick_ms += 1000U;
    assert(gps_get_last_trusted(&out));
    assert(out.month==2 && out.day==29 && out.hour==0 && out.second==0);
    gps_apply_ntp_utc(2026, 12, 31, 23, 59, 59);
    g_tick_ms += 2000U;
    assert(gps_get_last_trusted(&out));
    assert(out.year==2027 && out.month==1 && out.day==1 && out.second==1);
    /* A new valid fix resets the anchor; old fixes cannot rewind it. */
    selected.year=2027; selected.month=1; selected.day=1;
    selected.hour=0; selected.minute=0; selected.second=5;
    selected.last_update_ms=g_tick_ms;
    assert(gps_capture_last_trusted_snapshot(&selected));
    g_tick_ms += 2500;
    assert(gps_get_last_trusted(&out) && out.second==7);
    assert(!gps_capture_last_trusted_snapshot(&selected));
    g_tick_ms += 500;
    assert(gps_get_last_trusted(&out) && out.second==8);
    gps_init();
    g_tick_ms += 30000;
    assert(!gps_get_last_trusted(&out));
'''

if __name__ == "__main__":
    base.HARNESS = base.HARNESS.replace(
        '    puts("test_gps_ntp_apply: C harness PASS");', CASES)
    raise SystemExit(base.main())
