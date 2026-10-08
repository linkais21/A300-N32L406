from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
HEADER = ROOT / "include" / "work_mode_sleep.h"
SLEEP = ROOT / "src" / "work_mode_sleep.c"
PWR_H = ROOT / "include" / "power_mgr.h"
PWR = ROOT / "src" / "power_mgr.c"
MAIN = ROOT / "src" / "main.c"
WORK = ROOT / "src" / "work_mode.c"
MAKEFILE = ROOT / "Makefile"


def read(path):
    assert path.exists(), f"missing {path.relative_to(ROOT)}"
    return path.read_text(encoding="utf-8")


def body(source, name):
    match = re.search(
        rf"(?:static\s+)?(?:bool|void|work_sleep_wake_t|pwr_state_t)\s+"
        rf"{name}\s*\([^)]*\)\s*\{{",
        source,
    )
    assert match, f"missing function {name}"
    start = match.end()
    depth = 1
    index = start
    while index < len(source) and depth:
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
        index += 1
    assert depth == 0, f"unterminated function {name}"
    return source[start:index - 1]


def test_stop1_public_api_and_wake_bits():
    header = read(HEADER)
    for item in [
        "WORK_SLEEP_WAKE_NONE = 0",
        "WORK_SLEEP_WAKE_RTC = 1u << 0",
        "WORK_SLEEP_WAKE_ACC = 1u << 1",
        "WORK_SLEEP_WAKE_VIBRATION = 1u << 2",
        "WORK_SLEEP_WAKE_SOS = 1u << 3",
        "WORK_SLEEP_WAKE_POWER = 1u << 4",
        "void work_mode_sleep_init(void);",
        "bool work_mode_sleep_ready(void);",
        "void work_mode_sleep_process(uint32_t next_service_ms,",
        "work_sleep_wake_t work_mode_sleep_take_wake(void);",
        "void work_mode_sleep_isr_wake(work_sleep_wake_t source);",
        "bool work_mode_sleep_is_in_stop1(void);",
    ]:
        assert item in header


def test_stop1_uses_rtc_alarm_a_with_15_second_cap_and_fallback():
    source = read(SLEEP)
    process = body(source, "work_mode_sleep_process")
    assert "WORK_MODE_SLEEP_MAX_SLICE_MS 15000U" in source
    assert "clamp_sleep_slice_ms(next_service_ms)" in process
    assert "RTC_A_ALARM" in source
    assert "RTC_SetAlarm(RTC_FORMAT_BIN, RTC_A_ALARM" in source
    assert "RTC_ConfigInt(RTC_INT_ALRA, ENABLE)" in source
    assert "RTC_EnableAlarm(RTC_A_ALARM, ENABLE)" in source
    assert "RTC_EnableAlarm(RTC_A_ALARM, DISABLE)" in source
    assert "RTCAlarm_IRQn" in source
    assert "EXTI_LINE18" in source
    assert "clear_wake_exti_pending()" in source
    assert "i2c_accel_prepare_wake_sampling()" in source
    assert "RCC_ConfigRtcClk" in source
    assert "RCC_EnableRtcClk(ENABLE)" in source
    assert "RTC_Init(&rtc)" in source
    assert "EXTI_LINE12" in source and "EXTI_LINE2" in source and "EXTI_LINE3" in source
    assert "EXTI3_IRQHandler" in source
    assert "work_mode_sleep_monotonic_s" in source
    assert "PWR_EnterStopState(PWR_REGULATOR_LOWPOWER, PWR_STOPENTRY_WFI)" in process
    assert "PWR_EnterSLEEPMode(0, PWR_STOPENTRY_WFI)" in source


def test_stop1_sleep_does_not_reinitialize_modem_before_service_window():
    source = read(SLEEP)
    process = body(source, "work_mode_sleep_process")
    stop = process.index("PWR_EnterStopState(PWR_REGULATOR_LOWPOWER, PWR_STOPENTRY_WFI)")
    service = process.index("service_online_window()", stop)
    assert "hw_restore_after_stop2()" not in process[stop:service]
    service_body = body(source, "service_online_window")
    assert service_body.index("ec800m_process()") < service_body.index("tcp_manager_process()")
    assert service_body.index("tcp_manager_process()") < service_body.index("jt808_process()")
    assert "at_config_process()" in service_body
    assert "sms_process()" in service_body
    assert "ec800m_power_off" not in source
    assert "ec800m_sleep_enable" in source
    assert "ec800m_sleep_disable" in source


def test_online_service_window_reloads_watchdog_between_services():
    source = read(SLEEP)
    service_body = body(source, "service_online_window")
    services = [
        "ec800m_process()",
        "tcp_manager_process()",
        "jt808_process()",
        "at_config_process()",
        "sms_process()",
    ]
    positions = [service_body.index(service) for service in services]
    for index, (start, end) in enumerate(zip(positions, positions[1:])):
        interval = service_body[start + len(services[index]):end]
        assert "IWDG_ReloadKey()" in interval


def test_stop1_admission_guards_busy_work():
    source = read(SLEEP)
    guard = source
    for item in [
        "ec800m_at_busy()",
        "ec800m_tcp_state(ch) == TCP_STATE_OPENING",
        "ext_flash_try_lock_now(EXT_FLASH_OWNER_CONFIG)",
        "fota_get_state()",
        "blind_zone_replay_busy()",
    ]:
        assert item in guard
    assert "FOTA_STATE_CONNECTING" in guard
    assert "FOTA_STATE_DOWNLOADING" in guard
    assert "FOTA_STATE_VERIFYING" in guard
    assert "FOTA_STATE_READY" in guard
    assert "FOTA_STATE_CHECK_CONNECTING" in guard
    assert "FOTA_STATE_CHECKING" in guard
    assert "FOTA_STATE_PREPARING" in guard


def test_main_keeps_ota_receive_registration_after_modem_reset():
    source = read(MAIN)
    assert source.index("ec800m_init();") < source.index("fota_init();")


def test_stop1_emits_bounded_admission_and_wake_diagnostics():
    source = read(SLEEP)
    assert '[STOP] admission=BLOCK reason=' in source
    assert '[STOP1] enter slice_ms=' in source
    assert '[STOP1] wake' in source


def test_legacy_power_manager_is_only_compatibility_routing():
    header = read(PWR_H)
    source = read(PWR)
    assert '#include "work_mode_sleep.h"' in header
    assert "WORK_MODE_SLEEP_LEGACY_POWER_MGR" in source
    assert "IDLE_TIMEOUT_S" not in source
    assert "SLEEP_TIMEOUT_S" not in source
    assert "DEEP_SLEEP_TIMEOUT_S" not in source
    assert "RTC_WAKE_INTERVAL_S" not in source
    assert "ec800m_power_off" not in source
    assert "ec800m_sleep_enable" not in source
    assert "PWR_EnterSTOP2Mode" not in source
    assert "PWR_EnterStopState" not in source
    assert "pwr_acc_isr" in source and "WORK_SLEEP_WAKE_ACC" in source
    assert "pwr_sos_isr" in source and "WORK_SLEEP_WAKE_SOS" in source
    assert "pwr_charge_isr" in source and "WORK_SLEEP_WAKE_POWER" in source


def test_main_integrates_work_mode_and_alarm_routing():
    main = read(MAIN)
    makefile = read(MAKEFILE)
    assert "src/work_mode.c" in makefile
    assert "src/work_mode_sleep.c" in makefile
    assert "work_mode_init(" in main
    assert "work_mode_process(void)" in main
    assert "work_mode_notify_alarm(ALM_EMERGENCY_SOS)" in main
    assert "work_mode_notify_alarm(ALM_POWER_CUT)" in main
    assert "work_mode_notify_alarm(ALM_POWER_LOW)" in main
    assert "input.acc_high = hw_acc_is_on();" in main
    assert "input.gps_valid = jt808_location_snapshot_valid(" in main
    assert "pwr_process();" not in main


def test_vibration_wake_holds_awake_for_confirmation():
    main = read(MAIN)
    # A DA218E interrupt wake must keep the MCU out of the next WFI while
    # the policy accumulates the configured six-second confirmation window.
    assert "WORK_SLEEP_WAKE_VIBRATION" in main
    assert "vibration_wake_hold" in main
    assert "!vibration_wake_hold" in main
    assert "vibration_wake_samples" in main
    assert "vibration_wake_samples < 30U" in main
    assert "if (input.vibration_sample_valid)" in main
    assert "vibration_wake_window && vibration_wake_samples < 30U" in main


def test_vibration_confirmation_tolerates_single_missed_sample():
    source = read(WORK)
    assert "WORK_MODE_VIBRATION_MAX_GAP_MS 1000U" in source
    assert "vibration_hits_required" in source


def test_stop1_wake_is_preserved_for_next_work_mode_step():
    source = read(SLEEP)
    process = body(source, "work_mode_sleep_process")
    wake_call = process.index("PWR_EnterStopState")
    service_call = process.index("service_online_window", wake_call)
    assert "s_wake = WORK_SLEEP_WAKE_NONE" not in process[wake_call:service_call]


def test_sleep_clears_level_triggered_exti_pending_bits():
    source = read(SLEEP)
    main = read(MAIN)
    process = body(source, "work_mode_sleep_process")
    assert "EXTI_ClrITPendBit(EXTI_LINE12)" in process
    assert "EXTI_ClrITPendBit(EXTI_LINE3)" in process
    assert "NVIC_ClearPendingIRQ(EXTI15_10_IRQn)" in source
    assert "NVIC_ClearPendingIRQ(EXTI3_IRQn)" in source
    assert "NVIC_ClearPendingIRQ(EXTI2_IRQn)" in source
    assert "NVIC_ClearPendingIRQ(RTCAlarm_IRQn)" in source
    assert "[ACC] edge" in main
    assert "[WORK] logical_acc=" in main


if __name__ == "__main__":
    test_stop1_public_api_and_wake_bits()
    test_stop1_uses_rtc_alarm_a_with_15_second_cap_and_fallback()
    test_stop1_sleep_does_not_reinitialize_modem_before_service_window()
    test_online_service_window_reloads_watchdog_between_services()
    test_stop1_admission_guards_busy_work()
    test_main_keeps_ota_receive_registration_after_modem_reset()
    test_stop1_emits_bounded_admission_and_wake_diagnostics()
    test_legacy_power_manager_is_only_compatibility_routing()
    test_main_integrates_work_mode_and_alarm_routing()
    test_vibration_wake_holds_awake_for_confirmation()
    test_sleep_clears_level_triggered_exti_pending_bits()
    print("test_work_mode_contract: PASS")
