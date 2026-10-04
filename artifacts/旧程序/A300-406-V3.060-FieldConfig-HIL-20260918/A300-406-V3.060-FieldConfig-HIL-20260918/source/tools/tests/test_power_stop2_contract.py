from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PWR = (ROOT / "src" / "work_mode_sleep.c").read_text(encoding="utf-8")
HW = (ROOT / "src" / "hw_init.c").read_text(encoding="utf-8")


def test_stop1_uses_non_resetting_sleep_and_rtc_wake():
    assert "PWR_EnterStopState(PWR_REGULATOR_LOWPOWER, PWR_STOPENTRY_WFI)" in PWR
    assert "PWR_EnterSLEEPMode(0, PWR_STOPENTRY_WFI)" in PWR
    assert "stop1_admission_ready()" in PWR


def test_requested_stop1_path_does_not_enter_stop2():
    # N32L40x's published SDK has no STOP1 entry. Keep the online session in
    # the non-resetting sleep path until a STOP1 register contract is supplied.
    assert "PWR_EnterSTOP2Mode" not in PWR
    assert "FLASH_GetUserOB" not in PWR
    assert "PWR_EnterSLEEPMode(0, PWR_STOPENTRY_WFI)" in PWR
    assert "PWR_EnterStopState" in PWR


def test_sleep_time_uses_actual_rtc_wake_reason():
    # External ACC/SOS wakes may interrupt a slice early. Only an RTC alarm
    # represents completion of the requested interval.
    assert "wake_reason" in PWR
    assert "WORK_SLEEP_WAKE_RTC" in PWR
    assert "if ((wake_reason & WORK_SLEEP_WAKE_RTC) != 0U)" in PWR


def test_stop1_masks_periodic_interrupts_while_sleeping():
    # WFI must not be released by the 1 ms SysTick/TIM8 or GPS/debug receive
    # interrupts.  RTC, ACC/G-sensor and modem RX remain enabled as wake paths.
    assert "SysTick->CTRL" in PWR
    assert "NVIC_DisableIRQ(TIM8_UP_IRQn)" in PWR
    assert "NVIC_DisableIRQ(UART4_IRQn)" in PWR
    assert "NVIC_DisableIRQ(USART1_IRQn)" in PWR
    assert "NVIC_EnableIRQ(TIM8_UP_IRQn)" in PWR
    assert "NVIC_EnableIRQ(UART4_IRQn)" in PWR
    assert "NVIC_EnableIRQ(USART1_IRQn)" in PWR


def test_stop1_entry_log_is_not_emitted_for_every_rtc_slice():
    assert "s_stop1_log_active" in PWR
    assert "if (!s_stop1_log_active)" in PWR


if __name__ == "__main__":
    test_stop1_uses_non_resetting_sleep_and_rtc_wake()
    test_requested_stop1_path_does_not_enter_stop2()
    test_sleep_time_uses_actual_rtc_wake_reason()
    test_stop1_masks_periodic_interrupts_while_sleeping()
    test_stop1_entry_log_is_not_emitted_for_every_rtc_slice()
    print("test_power_stop2_contract: PASS")
