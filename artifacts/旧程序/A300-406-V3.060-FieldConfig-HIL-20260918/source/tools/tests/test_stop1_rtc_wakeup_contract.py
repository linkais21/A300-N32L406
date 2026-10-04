from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "src" / "work_mode_sleep.c").read_text(encoding="utf-8")


def test_rtc_alarm_irq_clears_rtc_alarm_flag_before_return():
    handler_start = SOURCE.index("void RTCAlarm_IRQHandler")
    handler_end = SOURCE.index("void EXTI3_IRQHandler", handler_start)
    handler = SOURCE[handler_start:handler_end]
    assert "RTC_GetITStatus(RTC_INT_ALRA)" in handler
    assert "RTC_ClrIntPendingBit(RTC_INT_ALRA)" in handler
    assert "RTC_ClrFlag(RTC_FLAG_ALAF)" in handler
    assert handler.index("RTC_GetITStatus(RTC_INT_ALRA)") < handler.index("RTC_ClrIntPendingBit(RTC_INT_ALRA)")
    assert "s_wake |= WORK_SLEEP_WAKE_RTC" in handler


def test_stop1_rtc_wakeup_is_not_consumed_before_main_loop():
    process = SOURCE[SOURCE.index("void work_mode_sleep_process"):SOURCE.index("void RTCAlarm_IRQHandler")]
    assert "wake_reason = s_wake" in process
    assert "s_wake = WORK_SLEEP_WAKE_NONE" not in process[process.index("wake_reason = s_wake"):]


def test_rtc_alarm_clear_resets_alarm_flag_for_next_slice():
    clear_start = SOURCE.index("static void rtc_alarm_clear")
    clear_end = SOURCE.index("static bool rtc_alarm_setup", clear_start)
    clear = SOURCE[clear_start:clear_end]
    assert "RTC_ClrFlag(RTC_FLAG_ALAF)" in clear
