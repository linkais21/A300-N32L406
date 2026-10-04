#include "work_mode_sleep.h"
#include "work_mode.h"
#include "hw_init.h"
#include "ec800m.h"
#include "cfg_query.h"
#include "tcp_manager.h"
#include "jt808.h"
#include "fota.h"
#include "blind_zone_replay.h"
#include "ext_flash_store.h"
#include "n32l40x.h"
#include "n32l40x_rtc.h"
#include "n32l40x_pwr.h"
#include "n32l40x_exti.h"
#include "n32l40x_dma.h"
#include "n32l40x_usart.h"
#include "n32l40x_spi.h"
#include "n32l40x_adc.h"
#include "config.h"
#include "at_config.h"
#include "peripherals.h"
#include "debug_uart.h"
#include "i2c_accel.h"

#define WORK_MODE_SLEEP_MAX_SLICE_MS 15000U
/* Slices between repeats of the retained-position line while asleep. At the
 * 15 s slice above this is one line every ~3 min, matching the stationary
 * reporting period instead of one per slice. */
#define STOP1_HISTORICAL_LOG_SLICES 12U

/* Must match the switch in main.c. Printed once at boot below so a field log
 * unambiguously shows which sleep profile the running binary was built with,
 * instead of relying on the build-date banner (a static macro that a plain
 * rebuild does not regenerate) or on a log line that only fires after a
 * STOP1 episode has actually happened. */
#ifndef A300_STOP1_SLEEP
#define A300_STOP1_SLEEP 0
#endif

static volatile work_sleep_wake_t s_wake;
static bool s_ready;
static bool s_in_stop1;
static volatile uint32_t s_sleep_seconds;
static uint32_t s_rtc_start_sod;
static bool s_accel_level_wake_latched;
/* PA12 level captured when the ACC wake was raised, so the filter does not
 * have to re-sample a pin that may be mid-bounce. */
static volatile bool s_acc_on_at_wake;

static uint32_t stop1_account_rtc_elapsed(uint32_t fallback_seconds)
{
    RTC_TimeType now;
    uint32_t sod;
    uint32_t elapsed;
    RTC_GetTime(RTC_FORMAT_BIN, &now);
    sod = (uint32_t)now.Hours * 3600U +
          (uint32_t)now.Minutes * 60U + now.Seconds;
    elapsed = (sod + 86400U - s_rtc_start_sod) % 86400U;
    return elapsed == 0U ? fallback_seconds : elapsed;
}
static uint32_t s_last_admission_log_ms;

static void clear_wake_exti_pending(void)
{
    EXTI_ClrITPendBit(EXTI_LINE12);
    EXTI_ClrITPendBit(EXTI_LINE3);
    EXTI_ClrITPendBit(EXTI_LINE2);
    EXTI_ClrITPendBit(EXTI_LINE18);
    NVIC_ClearPendingIRQ(EXTI15_10_IRQn);
    NVIC_ClearPendingIRQ(EXTI3_IRQn);
    NVIC_ClearPendingIRQ(EXTI2_IRQn);
    NVIC_ClearPendingIRQ(RTCAlarm_IRQn);
}
static uint32_t s_systick_ctrl;
static bool s_stop1_log_active;
static uint32_t s_stop1_slice_count;
static uint32_t s_last_alarm_fail_log_ms;
static uint32_t s_alarm_retry_after_ms;

/* Keep the A300 low-power ownership boundary: the modem is put into QSCLK
 * sleep first, then its UART/DMA receive path is quiesced for the WFI slice.
 * Restore the channel before servicing the modem after wake. */
static void stop1_suspend_modem_io(void)
{
    USART_EnableDMA(EC800M_UART, USART_DMAREQ_RX, DISABLE);
    DMA_ConfigInt(EC800M_DMA_CH_RX, DMA_INT_HTX | DMA_INT_TXC, DISABLE);
    DMA_EnableChannel(EC800M_DMA_CH_RX, DISABLE);
    NVIC_DisableIRQ(DMA_Channel5_IRQn);
    NVIC_ClearPendingIRQ(DMA_Channel5_IRQn);
    NVIC_DisableIRQ(UART5_IRQn);
    NVIC_ClearPendingIRQ(UART5_IRQn);
    USART_Enable(EC800M_UART, DISABLE);
}

static void stop1_resume_modem_io(void)
{
    DMA_ClearFlag(DMA_FLAG_HT5, DMA);
    DMA_ClearFlag(DMA_FLAG_TC5, DMA);
    DMA_ConfigInt(EC800M_DMA_CH_RX, DMA_INT_HTX | DMA_INT_TXC, ENABLE);
    DMA_EnableChannel(EC800M_DMA_CH_RX, ENABLE);
    USART_EnableDMA(EC800M_UART, USART_DMAREQ_RX, ENABLE);
    USART_Enable(EC800M_UART, ENABLE);
    NVIC_EnableIRQ(DMA_Channel5_IRQn);
}

/* Match A300's peripheral quiesce boundary.  No flash transaction is allowed
 * past admission, so gating the idle SPI/ADC blocks is safe and keeps their
 * clocks from generating activity during the WFI slice. */
static void stop1_suspend_local_peripherals(void)
{
    SPI_Enable(FLASH_SPI, DISABLE);
    ADC_Enable(ADC, DISABLE);
}

static void stop1_resume_local_peripherals(void)
{
    ADC_Enable(ADC, ENABLE);
    SPI_Enable(FLASH_SPI, ENABLE);
}

/* Ordinary SLEEP/WFI returns on every enabled interrupt.  Suspend periodic
 * timers and local receive sources for the low-power window; RTC and external
 * wake lines remain enabled while the modem UART/DMA path is quiesced. */
static void stop1_suspend_periodic_irqs(void)
{
    s_systick_ctrl = SysTick->CTRL;
    SysTick->CTRL &= ~(SysTick_CTRL_TICKINT_Msk | SysTick_CTRL_ENABLE_Msk);
    NVIC_DisableIRQ(TIM8_UP_IRQn);
    NVIC_ClearPendingIRQ(TIM8_UP_IRQn);
    NVIC_DisableIRQ(UART4_IRQn);
    NVIC_ClearPendingIRQ(UART4_IRQn);
    NVIC_DisableIRQ(USART1_IRQn);
    NVIC_ClearPendingIRQ(USART1_IRQn);
}

static void stop1_resume_periodic_irqs(void)
{
    NVIC_ClearPendingIRQ(TIM8_UP_IRQn);
    NVIC_ClearPendingIRQ(UART4_IRQn);
    NVIC_ClearPendingIRQ(USART1_IRQn);
    NVIC_EnableIRQ(TIM8_UP_IRQn);
    NVIC_EnableIRQ(UART4_IRQn);
    NVIC_EnableIRQ(USART1_IRQn);
    SysTick->CTRL = s_systick_ctrl;
}

/* The N32L40x SDK exposes no STOP1 entry or documented STOP1 register value.
 * Use non-resetting SLEEP/WFI for the online STOP1 window. */
void PWR_EnterStopState(uint32_t regulator, uint8_t entry)
{
    (void)regulator;
    PWR_EnterSLEEPMode(0U, entry);
}

static void setup_wake_exti(uint32_t line, uint8_t port_src, uint8_t pin_src,
                            EXTI_TriggerType trigger, IRQn_Type irqn)
{
    EXTI_InitType exti;
    NVIC_InitType nvic;
    GPIO_ConfigEXTILine(port_src, pin_src);
    EXTI_InitStruct(&exti);
    exti.EXTI_Line = line;
    exti.EXTI_Mode = EXTI_Mode_Interrupt;
    exti.EXTI_Trigger = trigger;
    exti.EXTI_LineCmd = ENABLE;
    EXTI_InitPeripheral(&exti);
    nvic.NVIC_IRQChannel = irqn;
    nvic.NVIC_IRQChannelPreemptionPriority = 1;
    nvic.NVIC_IRQChannelSubPriority = 0;
    nvic.NVIC_IRQChannelCmd = ENABLE;
    NVIC_Init(&nvic);
}

static uint32_t clamp_sleep_slice_ms(uint32_t requested_ms)
{
    if (requested_ms == 0U) return 1000U;
    return requested_ms > WORK_MODE_SLEEP_MAX_SLICE_MS ?
           WORK_MODE_SLEEP_MAX_SLICE_MS : requested_ms;
}

static bool ec800m_at_busy(void)
{
    ec800m_state_t state = ec800m_get_state();
    return state == EC800M_STATE_BOOTING || state == EC800M_STATE_INIT ||
           state == EC800M_STATE_SIM_CHECK || state == EC800M_STATE_NETWORK_REG ||
           state == EC800M_STATE_PDP_ACTIVE;
}

static const char *stop1_admission_block_reason(void)
{
    fota_state_t fota = fota_get_state();
    uint8_t ch;
    if (!jt808_is_online()) return "JT808";
    if (ec800m_at_busy()) return "EC800M";
    if (cfg_query_is_busy()) return "CFGQ";
    for (ch = 0U; ch < EC800M_CH_MAX; ++ch)
        if (ec800m_tcp_state(ch) == TCP_STATE_OPENING) return "TCP";
    if (!ext_flash_try_lock_now(EXT_FLASH_OWNER_CONFIG)) return "FLASH";
    ext_flash_unlock(EXT_FLASH_OWNER_CONFIG);
    if (fota == FOTA_STATE_CHECK_CONNECTING || fota == FOTA_STATE_CHECKING ||
        fota == FOTA_STATE_PREPARING ||
        fota == FOTA_STATE_CONNECTING || fota == FOTA_STATE_DOWNLOADING ||
        fota == FOTA_STATE_VERIFYING || fota == FOTA_STATE_READY) return "FOTA";
    if (blind_zone_replay_busy()) return "BLIND_REPLAY";
    return 0;
}

static bool stop1_admission_ready(void)
{
    return stop1_admission_block_reason() == 0;
}

static void rtc_alarm_clear(void)
{
    RTC_EnableAlarm(RTC_A_ALARM, DISABLE);
    RTC_ConfigInt(RTC_INT_ALRA, DISABLE);
    RTC_ClrIntPendingBit(RTC_INT_ALRA);
    RTC_ClrFlag(RTC_FLAG_ALAF);
    EXTI_ClrITPendBit(EXTI_LINE18);
    NVIC_ClearPendingIRQ(RTCAlarm_IRQn);
}

static bool rtc_alarm_setup(uint32_t slice_ms)
{
    RTC_TimeType now;
    RTC_AlarmType alarm;
    RTC_AlarmType verify;
    uint32_t seconds = (slice_ms + 999U) / 1000U;
    uint32_t target_seconds;
    RTC_GetTime(RTC_FORMAT_BIN, &now);
    s_rtc_start_sod = (uint32_t)now.Hours * 3600U +
                      (uint32_t)now.Minutes * 60U + now.Seconds;
    RTC_AlarmStructInit(&alarm);
    alarm.AlarmTime.H12 = RTC_AM_H12;
    target_seconds = ((uint32_t)now.Hours * 3600U) +
                     ((uint32_t)now.Minutes * 60U) +
                     (uint32_t)now.Seconds + seconds;
    target_seconds %= 86400U;
    alarm.AlarmTime.Hours = (uint8_t)(target_seconds / 3600U);
    alarm.AlarmTime.Minutes = (uint8_t)((target_seconds % 3600U) / 60U);
    alarm.AlarmTime.Seconds = (uint8_t)(target_seconds % 60U);
    alarm.DateWeekMode = RTC_ALARM_SEL_WEEKDAY_DATE;
    alarm.DateWeekValue = 1U;
    rtc_alarm_clear();
    /* Compare complete HH:MM:SS; only the calendar weekday is irrelevant. */
    alarm.AlarmMask = RTC_ALARMMASK_WEEKDAY;
    RTC_SetAlarm(RTC_FORMAT_BIN, RTC_A_ALARM, &alarm);
    RTC_GetAlarm(RTC_FORMAT_BIN, RTC_A_ALARM, &verify);
    /* Some N32L40x revisions normalize reserved alarm-mask bits on readback.
     * The write is authoritative; strict mask comparison would reject a
     * valid alarm and strand the device in fallback WFI forever. */
    if (verify.AlarmTime.Hours != alarm.AlarmTime.Hours ||
        verify.AlarmTime.Minutes != alarm.AlarmTime.Minutes ||
        verify.AlarmTime.Seconds != alarm.AlarmTime.Seconds) {
        dbg_printf("[STOP1] rtc alarm time readback mismatch want=%02u:%02u:%02u got=%02u:%02u:%02u\r\n",
                   (unsigned)alarm.AlarmTime.Hours,
                   (unsigned)alarm.AlarmTime.Minutes,
                   (unsigned)alarm.AlarmTime.Seconds,
                   (unsigned)verify.AlarmTime.Hours,
                   (unsigned)verify.AlarmTime.Minutes,
                   (unsigned)verify.AlarmTime.Seconds);
    }
    NVIC_ClearPendingIRQ(RTCAlarm_IRQn);
    RTC_ConfigInt(RTC_INT_ALRA, ENABLE);
    if (RTC_EnableAlarm(RTC_A_ALARM, ENABLE) != SUCCESS) {
        dbg_printf("[STOP1] rtc alarm enable failed ctrl=%08lx initsts=%08lx\r\n",
                   (unsigned long)RTC->CTRL, (unsigned long)RTC->INITSTS);
        rtc_alarm_clear();
        return false;
    }
    return true;
}

static void service_online_window(void)
{
    ec800m_process();
    IWDG_ReloadKey();
    tcp_manager_process();
    IWDG_ReloadKey();
    jt808_process();
    IWDG_ReloadKey();
    at_config_process();
    IWDG_ReloadKey();
    sms_process();
}

void work_mode_sleep_init(void)
{
    EXTI_InitType exti;
    NVIC_InitType nvic;
    RTC_InitType rtc;
    RCC_EnableAPB1PeriphClk(RCC_APB1_PERIPH_PWR, ENABLE);
    PWR_BackupAccessEnable(ENABLE);
    RCC_ConfigRtcClk(RCC_RTCCLK_SRC_LSI);
    RCC_EnableRtcClk(ENABLE);
    RTC_StructInit(&rtc);
    /* RTC_StructInit() defaults (AsynchPrediv=0x7F, SynchPrediv=0xFF, /32768)
     * are calibrated for a 32.768kHz LSE crystal. This board has no LSE and
     * clocks the RTC from LSI (~41.8kHz per vendor N32L40x RTC/Alarm example),
     * so the LSE-tuned divisor makes the RTC run ~22% fast. Use the vendor's
     * own LSI-calibrated predivider (/128/331, ~41828Hz) instead so RTC
     * seconds track real time; this fixes the multi-minute STOP1 timestamp
     * overshoot instead of just masking it periodically. */
    rtc.RTC_AsynchPrediv = 0x7F;
    rtc.RTC_SynchPrediv = 0x14A;
    (void)RTC_Init(&rtc);
    setup_wake_exti(EXTI_LINE12, GPIOA_PORT_SOURCE, GPIO_PIN_SOURCE12,
                    EXTI_Trigger_Rising_Falling, EXTI15_10_IRQn);
    setup_wake_exti(EXTI_LINE2, GPIOA_PORT_SOURCE, GPIO_PIN_SOURCE2,
                    EXTI_Trigger_Falling, EXTI2_IRQn);
    setup_wake_exti(EXTI_LINE3, GPIOB_PORT_SOURCE, GPIO_PIN_SOURCE3,
                    EXTI_Trigger_Rising, EXTI3_IRQn);
    EXTI_InitStruct(&exti);
    exti.EXTI_Line = EXTI_LINE18;
    exti.EXTI_Mode = EXTI_Mode_Interrupt;
    exti.EXTI_Trigger = EXTI_Trigger_Rising;
    exti.EXTI_LineCmd = ENABLE;
    EXTI_InitPeripheral(&exti);
    nvic.NVIC_IRQChannel = RTCAlarm_IRQn;
    nvic.NVIC_IRQChannelPreemptionPriority = 2;
    nvic.NVIC_IRQChannelSubPriority = 0;
    nvic.NVIC_IRQChannelCmd = ENABLE;
    NVIC_Init(&nvic);
    rtc_alarm_clear();
    s_wake = WORK_SLEEP_WAKE_NONE;
    s_in_stop1 = false;
    s_sleep_seconds = 0U;
    s_last_admission_log_ms = 0U;
    s_systick_ctrl = 0U;
    s_stop1_log_active = false;
    s_stop1_slice_count = 0U;
    s_last_alarm_fail_log_ms = 0U;
    s_alarm_retry_after_ms = 0U;
    s_accel_level_wake_latched = false;
    s_acc_on_at_wake = false;
    s_ready = true;
    dbg_printf("[SLEEP] profile=%s\r\n", A300_STOP1_SLEEP ? "stop1" : "shallow");
}

bool work_mode_sleep_ready(void) { return s_ready; }

void work_mode_sleep_isr_wake(work_sleep_wake_t source)
{
    s_wake |= source;
    /* Sample PA12 here, while the edge that raised this wake is still the
     * level on the pin.  The filter below used to re-read the pin instead, and
     * during contact bounce it could read the opposite level and discard a
     * genuine ACC-ON wake -- a field capture showed
     * "ACC-off edge ignored as wake" logged while the same pass reported
     * pin_high=0 acc_on=1. */
    if ((source & WORK_SLEEP_WAKE_ACC) != 0U) {
        s_acc_on_at_wake = hw_acc_is_on();
    }
}

work_sleep_wake_t work_mode_sleep_take_wake(void)
{
    work_sleep_wake_t wake = s_wake;
    s_wake = WORK_SLEEP_WAKE_NONE;
    return wake;
}

bool work_mode_sleep_is_in_stop1(void) { return s_in_stop1; }
uint32_t work_mode_sleep_monotonic_s(void)
{
    return (TICK_MS() / 1000U) + s_sleep_seconds;
}

void work_mode_sleep_shallow(void)
{
    if (!s_ready) return;
    IWDG_ReloadKey();
    /* The default shallow profile bypasses STOP1 admission. Keep OTA's
     * modem/flash work awake, including the READY-to-reset interval, and do
     * not issue QSCLK teardown while that operation owns modem control. */
    if (tcp_manager_ota_active()) return;
    /* One-shot teardown of any STOP1 residue: an earlier deep-sleep episode
     * may have left the RTC alarm armed and the modem in QSCLK. Neither is
     * wanted here -- the modem must stay awake so a downlink (0x8103 and
     * friends) is serviced on the next main-loop pass, not on a slice
     * boundary. */
    if (s_stop1_log_active) {
        rtc_alarm_clear();
        ec800m_sleep_disable();
        s_stop1_log_active = false;
        s_stop1_slice_count = 0U;
        dbg_printf("[SLEEP] shallow window active (STOP1 disarmed)\r\n");
    }
    /* s_in_stop1 stays false: the device is reachable on every tick, so
     * log_platform/cfg_query must not treat this as deep sleep.
     *
     * s_wake is deliberately left alone. work_mode_process() consumes it via
     * work_mode_sleep_take_wake() before this runs, and clearing it again here
     * would drop an edge that landed in between. A still-pending interrupt
     * simply makes WFI fall through immediately, which is the wanted
     * behaviour. */
    /* Teardown above may consume a substantial portion of the watchdog
     * window; refresh immediately before entering WFI as well as on return. */
    IWDG_ReloadKey();
    __DSB();
    PWR_EnterSLEEPMode(0U, PWR_STOPENTRY_WFI);
    IWDG_ReloadKey();
}

void work_mode_sleep_process(uint32_t next_service_ms, work_sleep_wake_t pending_wake)
{
    uint32_t slice_ms;
    work_sleep_wake_t wake_reason;
    const char *block_reason;
    bool accel_level_wake = false;
    if (!s_ready) return;
    s_wake |= pending_wake;
    /* PA12 is configured for both edges.  The falling edge that caused the
     * transition into stationary sleep is not a wake request: while ACC is
     * still low it is only the confirmation of the sleep state.  Leaving this
     * bit latched would make every pass take the early-service path and keep
     * the RTC/STOP1 window from ever being entered. */
    if ((s_wake & WORK_SLEEP_WAKE_ACC) != 0U && !s_acc_on_at_wake) {
        s_wake &= (work_sleep_wake_t)~WORK_SLEEP_WAKE_ACC;
        dbg_printf("[STOP1] ACC-off edge ignored as wake\r\n");
    }
    if (s_wake != WORK_SLEEP_WAKE_NONE) {
        /* EXTI3 is level-held by DA218E while motion remains active. Consume
         * one edge and leave the latch set until PB3 returns low; otherwise
         * every main-loop pass re-enters this early-wake path and STOP1 is
         * never reached. */
        s_wake = WORK_SLEEP_WAKE_NONE;
        clear_wake_exti_pending();
        i2c_accel_prepare_wake_sampling();
        service_online_window();
        return;
    }
    if (!stop1_admission_ready()) {
        block_reason = stop1_admission_block_reason();
        if (TICK_MS() - s_last_admission_log_ms >= 5000U) {
            s_last_admission_log_ms = TICK_MS();
            dbg_printf("[STOP] admission=BLOCK reason=%s ec=%u fota=%u replay=%u\r\n",
                       block_reason, (unsigned)ec800m_get_state(),
                       (unsigned)fota_get_state(),
                       (unsigned)blind_zone_replay_busy());
        }
        EXTI_ClrITPendBit(EXTI_LINE12);
        EXTI_ClrITPendBit(EXTI_LINE3);
        clear_wake_exti_pending();
        IWDG_ReloadKey();
        PWR_EnterSLEEPMode(0, PWR_STOPENTRY_WFI);
        IWDG_ReloadKey();
        EXTI_ClrITPendBit(EXTI_LINE12);
        EXTI_ClrITPendBit(EXTI_LINE3);
        clear_wake_exti_pending();
        i2c_accel_prepare_wake_sampling();
        service_online_window();
        return;
    }
    if ((int32_t)(TICK_MS() - s_alarm_retry_after_ms) < 0)
        return;
    slice_ms = clamp_sleep_slice_ms(next_service_ms);
    if (!rtc_alarm_setup(slice_ms)) {
        s_alarm_retry_after_ms = TICK_MS() + 5000U;
        if ((uint32_t)(TICK_MS() - s_last_alarm_fail_log_ms) >= 5000U) {
            s_last_alarm_fail_log_ms = TICK_MS();
            dbg_printf("[STOP1] rtc alarm setup failed\r\n");
        }
        IWDG_ReloadKey();
        clear_wake_exti_pending();
        PWR_EnterSLEEPMode(0, PWR_STOPENTRY_WFI);
        IWDG_ReloadKey();
        clear_wake_exti_pending();
        i2c_accel_prepare_wake_sampling();
        s_wake = WORK_SLEEP_WAKE_NONE;
        service_online_window();
        return;
    }
    s_in_stop1 = true;
    if (!s_stop1_log_active) {
        dbg_printf("[STOP1] enter slice_ms=%lu\r\n", (unsigned long)slice_ms);
        s_stop1_log_active = true;
        /* New sleep episode: log the retained position on its first slice. */
        s_stop1_slice_count = 0U;
    }
    ec800m_sleep_enable();
    stop1_suspend_periodic_irqs();
    stop1_suspend_modem_io();
    stop1_suspend_local_peripherals();
    EXTI_ClrITPendBit(EXTI_LINE12);
    EXTI_ClrITPendBit(EXTI_LINE3);
    clear_wake_exti_pending();
    /* DA218E INT1 is level-held during sustained motion. Clearing EXTI3
     * while PB3 is already high would lose the only edge and re-enter WFI
     * forever, so latch it as a software wake and skip this slice. */
    if (GPIO_ReadInputDataBit(DA218E_INT1_PORT, DA218E_INT1_PIN) == Bit_SET &&
        !s_accel_level_wake_latched) {
        s_wake |= WORK_SLEEP_WAKE_VIBRATION;
        accel_level_wake = true;
        s_accel_level_wake_latched = true;
    } else if (GPIO_ReadInputDataBit(DA218E_INT1_PORT, DA218E_INT1_PIN) != Bit_SET) {
        s_accel_level_wake_latched = false;
    }
    IWDG_ReloadKey();
    if (!accel_level_wake)
        PWR_EnterStopState(PWR_REGULATOR_LOWPOWER, PWR_STOPENTRY_WFI);
    IWDG_ReloadKey();
    stop1_resume_modem_io();
    stop1_resume_local_peripherals();
    stop1_resume_periodic_irqs();
    s_in_stop1 = false;
    wake_reason = s_wake;
    rtc_alarm_clear();
    clear_wake_exti_pending();
    i2c_accel_prepare_wake_sampling();
    if (wake_reason != WORK_SLEEP_WAKE_NONE) {
        dbg_printf("[STOP1] wake source=stop1_wake reason=0x%02x pin_high=%u acc_on=%u logical_acc=%u\r\n",
                   (unsigned)wake_reason, (unsigned)hw_acc_pin_high(),
                   (unsigned)hw_acc_is_on(),
                   (unsigned)work_mode_logical_acc());
    }
    {
        /* Account the RTC interval on every STOP1 return, not only when the
         * ALRA flag survived the interrupt cleanup. PB3/ACC wake and a stale
         * EXTI race can otherwise leave the historical timestamp frozen. */
        uint32_t elapsed_seconds = stop1_account_rtc_elapsed(0U);
        if ((wake_reason & WORK_SLEEP_WAKE_RTC) != 0U) {
            /* The requested slice completed; the RTC reading above is the
             * authoritative elapsed-time source even if the alarm flag was
             * cleared while unwinding the wake path. */
            dbg_printf("[STOP1] rtc elapsed=%lu\r\n",
                       (unsigned long)elapsed_seconds);
        }
        if (elapsed_seconds != 0U) {
            s_sleep_seconds += elapsed_seconds;
            gps_advance_last_trusted_seconds(elapsed_seconds);
            /* One line per 15 s slice buried the interesting events in the
             * field capture.  The retained snapshot only advances its clock
             * while asleep, so echoing it every slice adds nothing: report it
             * on the first slice of a sleep episode and then only once per
             * reporting period, plus whenever a real event ends the episode
             * (handled by the non-RTC wake branch below). */
            ++s_stop1_slice_count;
            if (s_stop1_slice_count == 1U ||
                (s_stop1_slice_count % STOP1_HISTORICAL_LOG_SLICES) == 0U) {
                gps_data_t historical;
                if (gps_get_last_trusted(&historical)) {
                    dbg_printf("[GPS] STOP1 historical valid=%u fix=%u sats=%u lat_e7=%ld lon_e7=%ld time=%04u-%02u-%02u %02u:%02u:%02u\r\n",
                               (unsigned)historical.valid,
                               (unsigned)historical.fix_quality,
                               (unsigned)historical.satellites,
                               (long)(historical.lat * 10000000.0),
                               (long)(historical.lon * 10000000.0),
                               (unsigned)historical.year,
                               (unsigned)historical.month,
                               (unsigned)historical.day,
                               (unsigned)historical.hour,
                               (unsigned)historical.minute,
                               (unsigned)historical.second);
                }
            }
        }
    }
    if ((wake_reason & (WORK_SLEEP_WAKE_ACC | WORK_SLEEP_WAKE_VIBRATION |
                       WORK_SLEEP_WAKE_SOS | WORK_SLEEP_WAKE_POWER)) != 0U) {
        dbg_printf("[STOP1] wake source=0x%02x\r\n", (unsigned)wake_reason);
        s_stop1_log_active = false;
    }
    ec800m_sleep_disable();
    service_online_window();
}

void RTCAlarm_IRQHandler(void)
{
    if (RTC_GetITStatus(RTC_INT_ALRA) != RESET) {
        RTC_ClrIntPendingBit(RTC_INT_ALRA);
        RTC_ClrFlag(RTC_FLAG_ALAF);
        EXTI_ClrITPendBit(EXTI_LINE18);
        s_wake |= WORK_SLEEP_WAKE_RTC;
    }
}

void EXTI3_IRQHandler(void)
{
    if (EXTI_GetITStatus(EXTI_LINE3)) {
        EXTI_ClrITPendBit(EXTI_LINE3);
        work_mode_sleep_isr_wake(WORK_SLEEP_WAKE_VIBRATION);
    }
}
