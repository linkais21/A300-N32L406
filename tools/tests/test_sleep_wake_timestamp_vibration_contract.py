"""Regression contracts for STOP1 wake time and vibration confirmation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GPS = (ROOT / "src" / "gps.c").read_text(encoding="utf-8")
GPS_H = (ROOT / "include" / "gps.h").read_text(encoding="utf-8")
SLEEP = (ROOT / "src" / "work_mode_sleep.c").read_text(encoding="utf-8")
ACCEL = (ROOT / "src" / "i2c_accel.c").read_text(encoding="utf-8")
WORK = (ROOT / "src" / "work_mode.c").read_text(encoding="utf-8")


def test_historical_fix_time_can_be_advanced_after_stop():
    assert "gps_advance_last_trusted_seconds" in GPS_H
    assert "gps_advance_last_trusted_seconds" in GPS
    assert "gps_advance_last_trusted_seconds(elapsed_seconds)" in SLEEP
    assert "s_rtc_start_sod" in SLEEP
    assert "stop1_account_rtc_elapsed" in SLEEP
    assert "Account the RTC interval on every STOP1 return" in SLEEP


def test_vibration_episode_tolerates_short_ema_misses():
    assert "WORK_MODE_VIBRATION_MAX_GAP_MS 1000U" in WORK
    assert "vibration_hits_required" in WORK
    assert "return s_diag.vibration_hit;" in ACCEL
    assert "TICK_MS() - s_last_vibration_log_ms >= 5000U" in ACCEL


def test_stop_entry_latches_active_high_accel_level():
    assert "DA218E_INT1_PORT" in SLEEP
    assert "GPIO_ReadInputDataBit(DA218E_INT1_PORT, DA218E_INT1_PIN)" in SLEEP
    assert "WORK_SLEEP_WAKE_VIBRATION" in SLEEP


def test_first_post_wake_accel_interrupt_only_opens_sampling_window():
    MAIN = (ROOT / "src" / "main.c").read_text(encoding="utf-8")
    assert "WORK_SLEEP_WAKE_VIBRATION" in MAIN
    assert "input.vibration_hit = true" not in MAIN
    assert "vibration_wake_window = true" in MAIN


def test_wake_logs_gnss_snapshot_and_fix_quality():
    MAIN = (ROOT / "src" / "main.c").read_text(encoding="utf-8")
    SLEEP = (ROOT / "src" / "work_mode_sleep.c").read_text(encoding="utf-8")
    for text in (MAIN, SLEEP):
        assert "gps_get_data()" in text or "gps_get_last_trusted" in text
        assert "fix_quality" in text
        assert "lat" in text and "lon" in text
    assert "lat_e7=%ld" in MAIN
    assert "lon_e7=%ld" in MAIN
    assert "lat_e7=%ld" in SLEEP
    assert "lon_e7=%ld" in SLEEP


def test_stop1_entry_does_not_reinject_consumed_wake_event():
    MAIN = (ROOT / "src" / "main.c").read_text(encoding="utf-8")
    assert "work_mode_sleep_process(15000U, WORK_SLEEP_WAKE_NONE)" in MAIN


def test_gnss_integrity_log_is_rate_limited():
    MAIN = (ROOT / "src" / "main.c").read_text(encoding="utf-8")
    assert "GPS-INTEGRITY" in MAIN
    assert "last_gps_integrity_log_ms" in MAIN
    assert "TICK_MS() - last_gps_integrity_log_ms) >= 30000U" in MAIN


def test_acc_off_edge_does_not_block_stop1_admission():
    assert "hw_acc_is_on()" in SLEEP
    assert "WORK_SLEEP_WAKE_ACC" in SLEEP
    assert "ACC-off edge" in SLEEP
    assert "rtc alarm time readback mismatch" in SLEEP
    assert "rtc alarm enable failed" in SLEEP


def test_rtc_alarm_readback_cannot_permanently_block_stop1():
    assert "RTC_SetAlarm(RTC_FORMAT_BIN, RTC_A_ALARM" in SLEEP
    assert "RTC_EnableAlarm(RTC_A_ALARM, ENABLE)" in SLEEP


def test_accel_level_wake_is_latched_until_pin_releases():
    SLEEP = (ROOT / "src" / "work_mode_sleep.c").read_text(encoding="utf-8")
    assert "s_accel_level_wake_latched" in SLEEP
    assert "!s_accel_level_wake_latched" in SLEEP
    assert "s_accel_level_wake_latched = false" in SLEEP


if __name__ == "__main__":
    test_historical_fix_time_can_be_advanced_after_stop()
    test_vibration_episode_tolerates_short_ema_misses()
    print("sleep wake timestamp/vibration contract: PASS")
