#!/usr/bin/env python3
"""Source contracts for the A300 low-power/ACC alignment boundary.

These assertions deliberately describe the hardware-facing sleep contract.  The
policy state machine must only enqueue an action; the low-power adapter owns
modem sleep, UART/DMA quiescing, RTC alarm validation, and watchdog-safe WFI.
"""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]


def strip_comments(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    return re.sub(r"//[^\r\n]*", "", source)


WORK = strip_comments((ROOT / "src" / "work_mode.c").read_text(encoding="utf-8"))
SLEEP = strip_comments((ROOT / "src" / "work_mode_sleep.c").read_text(encoding="utf-8"))


def function_body(source: str, name: str) -> str:
    match = re.search(rf"\b{name}\s*\([^;]*?\)\s*\{{", source, re.S)
    if match is None:
        raise AssertionError(f"missing function body: {name}")
    start = match.end() - 1
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start + 1:index]
    raise AssertionError(f"unterminated function body: {name}")


def test_acc_off_policy_is_transport_agnostic():
    """ACC-OFF policy may enqueue STOP1, but cannot enter hardware sleep itself."""
    assert "work_mode_sleep_process" not in WORK
    assert "PWR_EnterSLEEPMode" not in WORK
    assert "PWR_EnterSTOP2Mode" not in WORK
    assert "WORK_ACTION_ENTER_STOP1" in WORK


def test_stop1_toggles_ec800m_modem_sleep():
    """STOP1 entry/exit must bracket the online modem's QSCLK/DTR contract."""
    assert "ec800m_sleep_enable()" in SLEEP
    assert "ec800m_sleep_disable()" in SLEEP


def test_stop1_quiesces_uart5_and_dma5():
    """UART5 RX and its DMA channel cannot continuously release WFI."""
    assert re.search(r"NVIC_DisableIRQ\(\s*UART5_IRQn\s*\)", SLEEP)
    dma_ch = r"(?:DMA2_CH5|EC800M_DMA_CH_RX)"
    assert re.search(rf"DMA_EnableChannel\(\s*{dma_ch}\s*,\s*DISABLE\s*\)", SLEEP)
    assert re.search(rf"DMA_ConfigInt\(\s*{dma_ch}\s*,", SLEEP)
    assert re.search(rf"DMA_EnableChannel\(\s*{dma_ch}\s*,\s*ENABLE\s*\)", SLEEP)


def test_stop1_quiesces_local_peripherals():
    """The A300 low-power path also gates ADC/SPI while the CPU is asleep."""
    assert "SPI_Enable(FLASH_SPI, DISABLE)" in SLEEP
    assert "SPI_Enable(FLASH_SPI, ENABLE)" in SLEEP
    assert "ADC_Enable(ADC, DISABLE)" in SLEEP
    assert "ADC_Enable(ADC, ENABLE)" in SLEEP


def test_rtc_alarm_is_read_back_and_pending_irq_cleared():
    """A programmed alarm must be read back before WFI and clear NVIC state."""
    setup = function_body(SLEEP, "rtc_alarm_setup")
    assert "RTC_SetAlarm" in setup
    assert "RTC_GetAlarm" in setup
    assert re.search(r"RTC_GetAlarm[\s\S]*RTC_A_ALARM", setup)
    assert "NVIC_ClearPendingIRQ(RTCAlarm_IRQn)" in SLEEP
    clear = function_body(SLEEP, "rtc_alarm_clear")
    assert "NVIC_ClearPendingIRQ(RTCAlarm_IRQn)" in clear


def test_rtc_alarm_uses_full_day_rollover():
    """Alarm scheduling must carry seconds over minute/hour/day boundaries."""
    setup = function_body(SLEEP, "rtc_alarm_setup")
    assert "86400U" in setup
    assert "target_seconds" in setup
    assert "alarm.AlarmTime.Hours =" in setup
    assert "alarm.AlarmTime.Minutes =" in setup


def test_stop1_requires_online_session():
    """A300 only enters its online sleep path after JT808 is established."""
    admission = function_body(SLEEP, "stop1_admission_block_reason")
    assert "jt808_is_online()" in admission


def test_watchdog_is_reloaded_around_each_wfi():
    """The watchdog window must cover every low-power entry and return path."""
    wfi_sites = [m.start() for m in re.finditer(
        r"(?:PWR_EnterSLEEPMode|PWR_EnterStopState)\([^;]*PWR_STOPENTRY_WFI", SLEEP)]
    assert wfi_sites, "no WFI sleep entry found"
    for site in wfi_sites:
        before = SLEEP[max(0, site - 180):site]
        after = SLEEP[site:site + 220]
        assert "IWDG_ReloadKey()" in before, "missing watchdog reload before WFI"
        assert "IWDG_ReloadKey()" in after, "missing watchdog reload after WFI"


def main() -> None:
    test_acc_off_policy_is_transport_agnostic()
    test_stop1_toggles_ec800m_modem_sleep()
    test_stop1_quiesces_uart5_and_dma5()
    test_stop1_quiesces_local_peripherals()
    test_rtc_alarm_is_read_back_and_pending_irq_cleared()
    test_rtc_alarm_uses_full_day_rollover()
    test_stop1_requires_online_session()
    test_watchdog_is_reloaded_around_each_wfi()
    print("test_a300_alignment_contract: PASS")


if __name__ == "__main__":
    main()
