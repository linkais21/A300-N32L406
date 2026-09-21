#include "config.h"
#include "build_version.h"  /* Auto-generated version info */
#include "hw_init.h"
#include "debug_uart.h"
#include "ec800m.h"
#include "gps.h"
#include "jt808.h"
#include "at_config.h"
#include "adc_monitor.h"
#include "spi_flash.h"
#include "relay.h"
#include "status_led.h"
#include "flash_config.h"
#include "tcp_manager.h"
#include "power_mgr.h"
#include "work_mode.h"
#include "work_mode_sleep.h"
#include "mileage.h"
#include "geofence.h"
#include "fota.h"
#include "agnss_manager.h"
#include "blind_zone.h"
#include "blind_zone_replay.h"
#include "agnss_vendor.h"
#include "i2c_accel.h"
#include "peripherals.h"
#include "reset_diag.h"
#include "ram_watermark.h"
#include "syscalls.h"
#include "log_platform.h"
#include "cfg_query.h"
#include "overspeed_policy.h"
#include "n32l40x.h"
#include <string.h>

/* ── Terminal info loaded from flash at runtime ───────────────────────────── */
static jt808_terminal_t s_terminal;
static overspeed_policy_t s_overspeed_policy;
static volatile bool s_iwdg_started;
static void sms_command_execute(const char *from, const char *text)
{
    uint16_t len = 0;
    while (len < SMS_COMMAND_MAX_LEN && text[len] != '\0') ++len;
    (void)at_config_execute_sms(from, (const uint8_t *)text, len);
}
static void agnss_network_rx(uint8_t ch, const uint8_t *data, uint16_t len)
{
    (void)gnss_vendor_network_rx(ch, data, len);
}

void ec800m_wait_service_hook(void)
{
    gps_process();
}

static void early_debug_uart_init(void)
{
    RCC_EnableAPB2PeriphClk(RCC_APB2_PERIPH_GPIOA |
                             RCC_APB2_PERIPH_GPIOB |
                             RCC_APB2_PERIPH_AFIO,
                             ENABLE);

    GPIO_InitType g;
    USART_InitType u;
    GPIO_InitStruct(&g);
    g.GPIO_Mode      = GPIO_Mode_AF_PP;
    g.GPIO_Slew_Rate = GPIO_Slew_Rate_High;
    g.GPIO_Current   = GPIO_DC_4mA;
    g.GPIO_Pull      = GPIO_Pull_Up;
    g.GPIO_Alternate = GPIO_AF4_USART1;

    g.Pin = DBG_TX_PIN;
    GPIO_InitPeripheral(DBG_TX_PORT, &g);

    g.Pin = DBG_RX_PIN;
    GPIO_InitPeripheral(DBG_RX_PORT, &g);

    RCC_EnableAPB2PeriphClk(DBG_UART_CLK, ENABLE);
    USART_StructInit(&u);
    u.BaudRate            = DBG_BAUD;
    u.WordLength          = USART_WL_8B;
    u.StopBits            = USART_STPB_1;
    u.Parity              = USART_PE_NO;
    u.HardwareFlowControl = USART_HFCTRL_NONE;
    u.Mode                = USART_MODE_RX | USART_MODE_TX;
    USART_Init(DBG_UART, &u);
    USART_Enable(DBG_UART, ENABLE);
}

void hardfault_capture(uint32_t *stacked)
    __attribute__((used, noinline, noreturn));
void hardfault_capture(uint32_t *stacked)
{
    uint32_t pc = stacked != NULL ? stacked[6] : 0U;
    uint32_t lr = stacked != NULL ? stacked[5] : 0U;
    reset_diag_record_fault(pc, lr, SCB->CFSR, SCB->HFSR);
    if (!s_iwdg_started)
        NVIC_SystemReset();
    /* Deliberately stop servicing IWDG. The watchdog performs the bounded
     * recovery reset while the backup record remains available to boot. */
    while (1) {
    }
}

void HardFault_Handler(void) __attribute__((naked));
void HardFault_Handler(void)
{
    __asm volatile (
        "tst lr, #4\n"
        "ite eq\n"
        "mrseq r0, msp\n"
        "mrsne r0, psp\n"
        "b hardfault_capture\n");
}

/* ── TIM8 update interrupt: 1 ms tick ────────────────────────────────────── */
void TIM8_UP_IRQHandler(void)
{
    if (TIM_GetIntStatus(TIM8, TIM_INT_UPDATE))
        TIM_ClrIntPendingBit(TIM8, TIM_INT_UPDATE);
}

/* EC800M RX uses circular DMA configured by hw_usart_init() in hw_init.c.
 * ec800m.c handles DMA events and drains the RX ring in foreground code. */

/* ── USART1 RX: debug/config commands on PA9/PA10 ─────────────────────────── */
void USART1_IRQHandler(void)
{
    if (USART_GetIntStatus(DBG_UART, USART_INT_RXDNE)) {
        uint8_t b = (uint8_t)USART_ReceiveData(DBG_UART);
        at_config_feed(b);
    }
}

static void enable_debug_rx_irq(void)
{
    USART_ConfigInt(DBG_UART, USART_INT_RXDNE, ENABLE);
    NVIC_InitType n;
    n.NVIC_IRQChannel                   = USART1_IRQn;
    n.NVIC_IRQChannelPreemptionPriority = 3;
    n.NVIC_IRQChannelSubPriority        = 0;
    n.NVIC_IRQChannelCmd                = ENABLE;
    NVIC_Init(&n);
}


extern uint32_t _ebss;
extern uint32_t _estack;

static void stack_paint(void)
{
    uint32_t sp;
    __asm volatile ("mov %0, sp" : "=r" (sp));
    uint32_t *p = &_ebss;
    while ((uint32_t)p < sp - 64u)
        *p++ = 0xAAAAAAAAu;
}

/* ── Periodic log: 60,000 ms tick gate; main-loop delays may extend it ───────────────────────────────── */
#define RAM_STATIC  ((uint32_t)(&_ebss) - 0x20000000u)  /* data+bss, compile-time constant */
#define RAM_TOTAL   (24u * 1024u)
#define RAM_AVAIL   (RAM_TOTAL - RAM_STATIC)             /* bytes shared by heap and stack */
#define STACK_MARGIN_MIN (4u * 1024u)
static volatile uint32_t s_stack_margin_fault;
static volatile bool s_work_vibration_hit;
static bool s_vibration_rearm_pending;
static bool s_vibration_rearm_fault;
static uint8_t s_vibration_rearm_attempts;
#define VIBRATION_REARM_MAX_ATTEMPTS 3U

static void vibration_rearm_process(void)
{
    if (!s_vibration_rearm_pending)
        return;
    if (i2c_accel_rearm_wake_interrupt()) {
        s_vibration_rearm_pending = false;
        s_vibration_rearm_fault = false;
        s_vibration_rearm_attempts = 0U;
        return;
    }
    if (s_vibration_rearm_attempts < VIBRATION_REARM_MAX_ATTEMPTS)
        ++s_vibration_rearm_attempts;
    if (s_vibration_rearm_attempts >= VIBRATION_REARM_MAX_ATTEMPTS) {
        s_vibration_rearm_pending = false;
        s_vibration_rearm_fault = true;
        dbg_printf("[VIB] interrupt rearm fault; shallow fallback\r\n");
    }
}

static const char *work_mode_state_name(work_mode_state_t state)
{
    switch (state) {
    case WORK_MODE_BOOT_MONITOR: return "BOOT";
    case WORK_MODE_REALTIME: return "REALTIME";
    case WORK_MODE_STATIONARY_SLEEP: return "SLEEP";
    default: return "UNKNOWN_STATE";
    }
}

#define NTP_RESYNC_INTERVAL_MS   (6UL * 3600UL * 1000UL)
#define NTP_RETRY_INTERVAL_MS    (5UL * 60UL * 1000UL)

/* Periodic clock drift correction for the retained STOP1 fix's timestamp.
 * Only ever writes s_last_trusted's date/time fields (via gps_apply_ntp_utc);
 * never touches position, fix validity, or sleep/wake state. */
static void ntp_resync_process(void)
{
    static uint32_t next_due_ms = 0;
    ec800m_time_t t;

    if (!ec800m_is_ready() || (int32_t)(TICK_MS() - next_due_ms) < 0) return;

    if (ec800m_ntp_sync(&t) && t.valid) {
        gps_apply_ntp_utc(t.year, t.month, t.day, t.hour, t.minute, t.second);
        next_due_ms = TICK_MS() + NTP_RESYNC_INTERVAL_MS;
        dbg_printf("[NTP] synced %04u-%02u-%02u %02u:%02u:%02u UTC\r\n",
                   t.year, t.month, t.day, t.hour, t.minute, t.second);
    } else {
        /* A silent failure branch made it impossible to tell from a field log
         * whether the sync ran at all, timed out, or failed to parse.  Report
         * the attempt and the retry backoff so the next capture is decisive. */
        next_due_ms = TICK_MS() + NTP_RETRY_INTERVAL_MS;
        dbg_printf("[NTP] sync failed valid=%u retry_in=%us\r\n",
                   (unsigned)t.valid,
                   (unsigned)(NTP_RETRY_INTERVAL_MS / 1000UL));
    }
}

static void periodic_status_log(void)
{
    static uint32_t last_ms = 0;
    if (TICK_MS() - last_ms < 60000) return;
    last_ms = TICK_MS();

    ram_watermark_t ram = {0U, 0U, 0U, RAM_AVAIL};
    const volatile gps_diag_t *gps_diag = gps_get_diag();
    const accel_diag_t *accel_diag = i2c_accel_get_diag();
    bool measured = ram_watermark_measure(&_ebss, sys_heap_break(), &_estack, &ram);
    if (!measured || ram.free_gap < STACK_MARGIN_MIN)
        s_stack_margin_fault = 1;
    dbg_printf("[HEALTH] 4G=%u S=%s R=%s REG=%d GPS=%u HEAP_USED=%u STK_PEAK=%u RAM_GAP=%u RAM_AVAIL=%u F=%u\r\n",
               ec800m_is_ready(), ec800m_state_name(ec800m_get_state()),
               ec800m_failure_name(ec800m_get_failure()), ec800m_get_reg_status(),
               gps_get_data()->valid,
               ram.heap_used, ram.stack_peak, ram.free_gap,
               ram.total_available, s_stack_margin_fault);
    dbg_printf("[GPS] RX=%lu SENT=%lu GGA=%lu RMC=%lu OK=%lu CS=%lu FMT=%lu NOFIX=%lu DROP=%lu QDROP=%lu LDROP=%lu OREF=%lu\r\n",
               (unsigned long)gps_diag->rx_bytes,
               (unsigned long)gps_diag->sentences,
               (unsigned long)gps_diag->gga,
               (unsigned long)gps_diag->rmc,
               (unsigned long)gps_diag->parsed,
               (unsigned long)gps_diag->checksum_fail,
               (unsigned long)gps_diag->format_fail,
               (unsigned long)gps_diag->no_fix,
               (unsigned long)gps_diag->drop,
               (unsigned long)gps_diag->drop_queue,
               (unsigned long)gps_diag->drop_length,
               (unsigned long)gps_diag->overrun);
    dbg_printf("[ACCEL] addr=0x%02x INT1=%u X=%d Y=%d Z=%d read_ok=%u samples=%lu fails=%lu delta=%u threshold=%u hits=%lu\r\n",
               accel_diag->address,
               (unsigned)GPIO_ReadInputDataBit(DA218E_INT1_PORT, DA218E_INT1_PIN),
               accel_diag->x, accel_diag->y, accel_diag->z,
               (unsigned)accel_diag->read_ok,
               (unsigned long)accel_diag->sample_count,
               (unsigned long)accel_diag->read_fail_count,
               (unsigned)accel_diag->delta, (unsigned)accel_diag->threshold,
               (unsigned long)accel_diag->vibration_hit_count);
    dbg_printf("[WORK] state=%s pin_high=%u acc_on=%u logical_acc=%u vib=%u hits=%u/%u stop=%u now=%lu\r\n",
               work_mode_state_name(work_mode_state()),
               (unsigned)hw_acc_pin_high(),
               (unsigned)hw_acc_is_on(),
               (unsigned)work_mode_logical_acc(),
               (unsigned)s_work_vibration_hit,
               (unsigned)work_mode_vibration_hits(),
               (unsigned)work_mode_vibration_required(),
               (unsigned)work_mode_sleep_is_in_stop1(),
               (unsigned long)work_mode_sleep_monotonic_s());
}

/* ── Alarm scanning ──────────────────────────────────────────────────────── */
static void scan_alarms(void)
{
    static bool sos_prev = false;
    bool sos_now = (GPIO_ReadInputDataBit(SOS_PORT, SOS_PIN) == Bit_RESET);
    if (sos_now && !sos_prev) {
        dbg_printf("[ALARM] SOS pressed\r\n");
        jt808_trigger_alarm(ALM_EMERGENCY_SOS);
        work_mode_notify_alarm(ALM_EMERGENCY_SOS);
    }
    sos_prev = sos_now;

    /* Power cut: car voltage absent while previously present */
    static bool car_prev = false;
    bool car_now = adc_is_car_powered();
    if (car_prev && !car_now) {
        dbg_printf("[ALARM] power cut detected\r\n");
        jt808_trigger_alarm(ALM_POWER_CUT);
        work_mode_notify_alarm(ALM_POWER_CUT);
    }
    car_prev = car_now;

    static bool bat_prev_low = false;
    bool bat_low = adc_is_bat_low();
    if (bat_low && !bat_prev_low) {
        jt808_trigger_alarm(ALM_POWER_LOW);
        work_mode_notify_alarm(ALM_POWER_LOW);
    }
    bat_prev_low = bat_low;

    {
        const gps_data_t *speed_gps = gps_get_data();
        uint32_t now_ms = TICK_MS();
        bool fresh_fix = jt808_location_snapshot_valid(speed_gps, now_ms);
        if (overspeed_policy_step(&s_overspeed_policy, now_ms,
                                  work_mode_state() == WORK_MODE_REALTIME,
                                  fresh_fix, speed_gps->speed_kmh,
                                  cfg_get()->speed_limit_kmh)) {
            dbg_printf("[ALARM] overspeed speed_x10=%u limit=%u\r\n",
                       (unsigned)(speed_gps->speed_kmh * 10.0f),
                       (unsigned)cfg_get()->speed_limit_kmh);
            jt808_trigger_alarm(ALM_OVERSPEED);
            work_mode_notify_alarm(ALM_OVERSPEED);
        }
    }
}

/* ── ACC state-change report de-bounce ───────────────────────────────────────
 * PA12 bounces on real vehicles: a field capture logged 191 edges and 21 mode
 * transitions in one session, several times flipping twice within the same
 * second.  Each flip queued an ACC entry report, so the platform received
 * alternating ACC ON/OFF frames and kept whichever arrived last -- one capture
 * showed ACC ON at 14:41:18 not settling until 14:42:07.
 *
 * The de-bounce lives here, in the reporting path, deliberately: the work-mode
 * state machine and its host tests pin ACC timing at 50 ms and at 5 s, leaving
 * no dwell window that both passes those contracts and outlasts a
 * multi-second bounce.  Reporting is where the symptom is, so that is where it
 * is filtered.
 *
 * Timing uses the STOP1-aware monotonic second, not TICK_MS(), because the
 * tick is suspended while asleep and bounce spans sleep entries.
 */
#define ACC_REPORT_SETTLE_S 5U
/* Upper bound on how long an ACC wake keeps the CPU out of STOP1 while the
 * PA12 debounce commits.  Four times WORK_MODE_ACC_DEBOUNCE_MS leaves room for
 * a bouncing pin without letting one that never settles hold sleep off. */
#define ACC_WAKE_HOLD_MS 2000U

/* Sleep profile.  A300_STOP1_SLEEP=1 restores the STOP1 deep-sleep path
 * (microamp floor, ACC detection bounded by the 15 s RTC slice).  The default 0
 * follows the validated reference profile: shallow WFI with SysTick running,
 * so the loop re-polls PA12 every 1 ms and ACC commits within ~50 ms.  Override
 * with EXTRA_CFLAGS=-DA300_STOP1_SLEEP=1. */
#ifndef A300_STOP1_SLEEP
#define A300_STOP1_SLEEP 0
#endif

/* Set by work_mode_process(), consumed at the main-loop tail: true while the
 * mode manager has nothing to do and no wake window is being held open. */
static bool s_shallow_sleep_allowed;
#if !A300_STOP1_SLEEP
static bool s_shallow_retained_clock_active;
static uint32_t s_shallow_retained_clock_s;

static void shallow_retained_clock_advance(uint32_t now_s)
{
    uint32_t elapsed_s;

    if (!s_shallow_retained_clock_active)
        return;
    elapsed_s = now_s - s_shallow_retained_clock_s;
    if (elapsed_s == 0U)
        return;
    gps_advance_last_trusted_seconds(elapsed_s);
    s_shallow_retained_clock_s = now_s;
}
#endif

static bool s_acc_report_valid;      /* an ACC level has been announced */
static bool s_acc_report_level;      /* the level last announced */
static uint32_t s_acc_report_s;      /* when it was announced */
static bool s_acc_report_deferred;   /* a reversal is waiting for the window */
static bool s_acc_report_pending;    /* the level that reversal carried */

/* True when this ACC entry report must not go out yet.  Called only for
 * WORK_ACTION_REPORT_ENTRY, whose acc_on carries the announced level. */
static bool acc_report_suppressed(bool acc_on, uint32_t now_s)
{
    if (!s_acc_report_valid) {
        s_acc_report_valid = true;
        s_acc_report_level = acc_on;
        s_acc_report_s = now_s;
        s_acc_report_deferred = false;
        return false;
    }
    if (acc_on == s_acc_report_level) {
        /* Same level as announced: the bounce came back to where it started,
         * so nothing further needs to be said. */
        s_acc_report_deferred = false;
        return true;
    }
    if ((uint32_t)(now_s - s_acc_report_s) < ACC_REPORT_SETTLE_S) {
        s_acc_report_deferred = true;
        s_acc_report_pending = acc_on;
        dbg_printf("[ACC] report deferred level=%u within %us settle\r\n",
                   (unsigned)acc_on, (unsigned)ACC_REPORT_SETTLE_S);
        return true;
    }
    /* Outside the window this is a genuine change; announce it. */
    s_acc_report_level = acc_on;
    s_acc_report_s = now_s;
    s_acc_report_deferred = false;
    return false;
}

/* Emit a level that was deferred once the settle window has passed and the
 * pin has actually stayed there, so a suppressed change is never simply lost. */
static void acc_report_settle(uint32_t now_s)
{
    if (!s_acc_report_deferred ||
        (uint32_t)(now_s - s_acc_report_s) < ACC_REPORT_SETTLE_S) {
        return;
    }
    s_acc_report_deferred = false;
    if (s_acc_report_pending == s_acc_report_level) return;
    if (hw_acc_is_on() != s_acc_report_pending) {
        /* The pin did not stay where the deferred edge left it; the level on
         * record is still correct. */
        return;
    }
    s_acc_report_level = s_acc_report_pending;
    s_acc_report_s = now_s;
    dbg_printf("[ACC] report settled level=%u\r\n",
               (unsigned)s_acc_report_pending);
    if (jt808_send_location_work_mode(0U, false) == JT808_SEND_NO_POSITION)
        (void)jt808_send_location_work_mode(0U, true);
}

void work_mode_process(void)
{
    static work_mode_state_t last_state = WORK_MODE_BOOT_MONITOR;
    work_mode_input_t input;
    work_mode_action_t action;
    work_sleep_wake_t wake = work_mode_sleep_take_wake();
    static uint8_t vibration_wake_samples;
    static bool vibration_wake_window;
    static uint32_t vibration_wake_started_ms;
    static uint32_t vibration_wake_last_hit_ms;
    static uint32_t last_gps_integrity_log_ms;
    static bool acc_wake_window;
    static uint32_t acc_wake_started_ms;
    bool vibration_wake_hold;
    bool acc_wake_hold;
    uint8_t processed = 0U;
    uint32_t now_s = work_mode_sleep_monotonic_s();
    if (wake != WORK_SLEEP_WAKE_NONE) {
        /* STOP1 suspends SysTick; make the first post-wake accelerometer
         * sample eligible before work-mode evaluates the wake window. */
        i2c_accel_prepare_wake_sampling();
    }
    if ((wake & WORK_SLEEP_WAKE_ACC) != 0U) {
        /* An ACC wake needs the CPU awake long enough for work_mode's 50 ms
         * PA12 debounce to commit, exactly as a vibration wake needs its
         * six-second confirmation.  Without this the loop below saw the state
         * still STATIONARY_SLEEP and re-entered STOP1 immediately, cutting the
         * debounce short: a field capture showed the wake and the ACC edge
         * recorded correctly, then "[STOP1] enter", and the mode transition
         * only after the next 15 s RTC slice -- reported as ACC ON taking
         * 22..45 s to reach the platform. */
        acc_wake_window = true;
        acc_wake_started_ms = TICK_MS();
    }
    input.now_s = now_s;
    input.now_ms = TICK_MS();
    input.acc_high = hw_acc_is_on();
    work_mode_acc_sample(input.acc_high, TICK_MS());
    {
        static bool last_acc_high;
        static bool acc_sample_initialized;
        if (!acc_sample_initialized || input.acc_high != last_acc_high) {
            dbg_printf("[ACC] edge pin_high=%u acc_on=%u logical_acc=%u\r\n",
                       (unsigned)hw_acc_pin_high(), (unsigned)input.acc_high,
                       (unsigned)work_mode_logical_acc());
            last_acc_high = input.acc_high;
            acc_sample_initialized = true;
        }
    }
    input.vibration_sample_valid = i2c_accel_vibration_sample_due();
    input.vibration_hit = input.vibration_sample_valid ?
                          i2c_accel_vibration_hit(cfg_get()->vib_sens) : false;
    /* The PB3 interrupt only opens a sampling window. It is not itself a
     * threshold hit and cannot authorize a realtime transition. */
    if ((wake & WORK_SLEEP_WAKE_VIBRATION) != 0U) {
        s_vibration_rearm_fault = false;
        s_vibration_rearm_attempts = 0U;
        vibration_wake_samples = 0U;
        vibration_wake_window = true;
        vibration_wake_started_ms = TICK_MS();
        vibration_wake_last_hit_ms = vibration_wake_started_ms;
    }
    if (input.vibration_sample_valid) {
        if (vibration_wake_window && vibration_wake_samples < 30U)
            ++vibration_wake_samples;
        if (vibration_wake_window && input.vibration_hit)
            vibration_wake_last_hit_ms = TICK_MS();
    }
    /* Keep the CPU out of WFI for the configured six-second confirmation
     * window.  The old sample-count gate stretched this window to ~30 s on
     * a busy modem loop because samples were not actually serviced every
     * 200 ms.  Confirmation is time based in work_mode; this gate only keeps
     * sampling alive until that deadline. */
    vibration_wake_hold = vibration_wake_window &&
        ((uint32_t)(TICK_MS() - vibration_wake_started_ms) < 6000U ||
         (uint32_t)(TICK_MS() - vibration_wake_last_hit_ms) <= 1000U);
    /* Hold off STOP1 until the PA12 debounce has had time to commit.  The
     * window is generous relative to WORK_MODE_ACC_DEBOUNCE_MS (500 ms) so a
     * bouncing pin still gets a decision, and bounded so a pin that never
     * settles cannot keep the device awake. */
    acc_wake_hold = acc_wake_window &&
        (uint32_t)(TICK_MS() - acc_wake_started_ms) < ACC_WAKE_HOLD_MS;
    if (work_mode_state() == WORK_MODE_REALTIME || !acc_wake_hold) {
        acc_wake_window = false;
        acc_wake_hold = false;
    }
    if (work_mode_state() == WORK_MODE_REALTIME ||
        !vibration_wake_hold) {
        /* Report an episode that woke the CPU but never reached the confirm
         * threshold: the wake source alone did not explain why the device
         * went straight back to sleep. */
        if (vibration_wake_window && work_mode_state() != WORK_MODE_REALTIME) {
            const accel_diag_t *vd = i2c_accel_get_diag();
            dbg_printf("[VIB] unconfirmed hits=%u/%u samples=%u delta=%u threshold=%u\r\n",
                       (unsigned)work_mode_vibration_hits(),
                       (unsigned)work_mode_vibration_required(),
                       (unsigned)vibration_wake_samples,
                       (unsigned)vd->delta, (unsigned)vd->threshold);
        }
        if (vibration_wake_window) {
            s_vibration_rearm_pending = true;
        }
        vibration_wake_window = false;
        vibration_wake_hold = false;
    }
    if (s_vibration_rearm_pending)
        vibration_rearm_process();
    s_work_vibration_hit = input.vibration_hit;
    input.rtc_wake = (wake & WORK_SLEEP_WAKE_RTC) != 0U;
    input.alarm_bits = work_mode_take_alarm();
    input.gps_valid = jt808_location_snapshot_valid(gps_get_data(),
                                                    input.now_ms);
    work_mode_step(&input);

    if (work_mode_state() == WORK_MODE_REALTIME &&
        (uint32_t)(TICK_MS() - last_gps_integrity_log_ms) >= 30000U) {
        const gps_data_t *g = gps_get_data();
        const char *quality = g->fix_quality == 4U ? "RTK" :
                              g->fix_quality == 2U ? "DGPS" :
                              g->fix_quality == 1U ? "SINGLE" : "NOFIX";
        last_gps_integrity_log_ms = TICK_MS();
        dbg_printf("[GPS-INTEGRITY] speed=%u.%u lat_e7=%ld lon_e7=%ld GNSS_Q=%u(%s) valid=%u sats=%u\r\n",
                   (unsigned)g->speed_kmh,
                   (unsigned)((uint16_t)(g->speed_kmh * 10.0f) % 10U),
                   (long)(g->lat * 10000000.0),
                   (long)(g->lon * 10000000.0),
                   (unsigned)g->fix_quality, quality,
                   (unsigned)g->valid, (unsigned)g->satellites);
    }

    /* Apply sleep priority before any action can block in STOP1. */
    status_led_process(work_mode_state() == WORK_MODE_STATIONARY_SLEEP,
                       gps_is_valid(), TICK_MS());

    if (work_mode_state() != last_state) {
        dbg_printf("[WORK] transition %s->%s now=%lu pin_high=%u acc_on=%u logical_acc=%u vib=%u\r\n",
                   work_mode_state_name(last_state),
                   work_mode_state_name(work_mode_state()),
                   (unsigned long)now_s, (unsigned)hw_acc_pin_high(),
                   (unsigned)input.acc_high,
                   (unsigned)work_mode_logical_acc(),
                   (unsigned)input.vibration_hit);
        if (work_mode_state() == WORK_MODE_STATIONARY_SLEEP)
            (void)mileage_force_save(TICK_MS());
        last_state = work_mode_state();
    }

    while (processed < 8U && work_mode_next_action(&action)) {
        ++processed;
        switch (action.type) {
        case WORK_ACTION_SET_LOGICAL_ACC:
            jt808_set_logical_acc(action.acc_on);
            dbg_printf("[WORK] logical_acc=%u applied\r\n", (unsigned)action.acc_on);
            break;
        case WORK_ACTION_GPS_ON:
#if !A300_STOP1_SLEEP
            /* SysTick keeps running in shallow sleep. Bring the retained UTC
             * up to the wake instant before an ACC-ON entry report can fall
             * back to that position while GNSS is reacquiring. */
            shallow_retained_clock_advance(now_s);
            s_shallow_retained_clock_active = false;
#endif
            gps_enable(true);
            gps_resume_after_wake();
            break;
        case WORK_ACTION_GPS_OFF:
            (void)gps_capture_last_trusted();
#if !A300_STOP1_SLEEP
            s_shallow_retained_clock_s = now_s;
            s_shallow_retained_clock_active = true;
#endif
            gps_enable(false);
            break;
        case WORK_ACTION_REPORT_ENTRY:
        case WORK_ACTION_REPORT_LOCATION:
        case WORK_ACTION_REPORT_ALARM: {
            int sent;
            /* An ACC state-change announcement is held back when it would
             * merely undo one just sent: PA12 contact bounce otherwise puts a
             * burst of alternating ACC ON/OFF reports on the wire and the
             * platform settles on whichever edge happened to be last.  The
             * first edge still reports immediately, so a real ACC change is
             * announced within a second; only a reversal inside the settle
             * window is deferred, and acc_report_settle() below emits the
             * level that actually persisted. */
            if (action.type == WORK_ACTION_REPORT_ENTRY &&
                acc_report_suppressed(action.acc_on, now_s)) {
                break;
            }
#if !A300_STOP1_SLEEP
            /* Keep configured stationary historical reports current even
             * though their coordinates remain the last trusted sleep fix. */
            shallow_retained_clock_advance(now_s);
#endif
            sent = jt808_send_location_work_mode(action.alarm_bits,
                                                 action.historical_position);
            /* Re-queue a transport failure, but never JT808_SEND_NO_POSITION:
             * that means GNSS has no fix and nothing was ever captured, which
             * only time can clear.  Retrying it immediately spun this loop at
             * full speed -- a field capture showed 1092 attempts and nothing
             * else in 1131 lines, because the blocking debug UART then starved
             * the very loop that would have acquired the fix.  The scheduler
             * re-arms this report on the next reporting deadline. */
            if (sent != 0 && sent != JT808_SEND_NO_POSITION) {
                work_mode_retry_action(&action);
                processed = 8U;
            }
            break;
        }
        case WORK_ACTION_REPORT_HEARTBEAT:
            if (jt808_send_heartbeat() != 0) {
                work_mode_retry_action(&action);
                processed = 8U;
            }
            break;
        case WORK_ACTION_ENTER_STOP1:
#if A300_STOP1_SLEEP
            /* `wake` has already been consumed above.  Passing it again as a
             * pending wake aborts STOP1 admission and can leave the unit in
             * GPS-off SLEEP forever (especially after a vibration wake). */
            if (relay_test_remaining() == 0U)
                work_mode_sleep_process(15000U, WORK_SLEEP_WAKE_NONE);
#endif
            /* The shallow profile decides at the main-loop tail, once every
             * _process() has had its pass, so the action only consumes the
             * wake here. */
            wake = WORK_SLEEP_WAKE_NONE;
            break;
        default:
            break;
        }
    }

    /* Release a deferred ACC level once the bounce has settled, before the
     * sleep decision below: a suppressed change must never be lost. */
    acc_report_settle(now_s);

#if A300_STOP1_SLEEP
    s_shallow_sleep_allowed = false;
    if (work_mode_state() == WORK_MODE_STATIONARY_SLEEP &&
        !vibration_wake_hold &&
        !acc_wake_hold &&
        !work_mode_sleep_is_in_stop1()) {
        if (s_vibration_rearm_pending) {
            /* Keep servicing the bounded retry state before another sleep
             * admission; no un-reset permanent INT1 latch is ignored. */
        } else if (s_vibration_rearm_fault) {
            /* Publish the shallow fallback for the main-loop tail. Sleeping
             * inside work_mode_process() would delay every later service. */
            s_shallow_sleep_allowed = true;
        } else {
            if (relay_test_remaining() == 0U)
                work_mode_sleep_process(15000U, wake);
        }
    }
#else
    /* Publish the decision instead of sleeping here.  work_mode_process() runs
     * mid-loop, so a WFI at this point would delay every _process() after it;
     * the validated reference profile sleeps at the loop tail.  The gate is
     * the same one STOP1 used: no sleep while an ACC or vibration hold is
     * keeping the debounce window open. */
    if (work_mode_state() == WORK_MODE_STATIONARY_SLEEP &&
        !vibration_wake_hold &&
        !acc_wake_hold &&
        !s_vibration_rearm_pending) {
        s_shallow_sleep_allowed = true;
    } else {
        s_shallow_sleep_allowed = false;
    }
    (void)wake;
#endif
}

static void log_hardware_contract(void)
{
    dbg_printf("[HW] ACC=PA12 pin_high=%u acc_on=%u logical_acc=%u CAR_ADC=PA3/CH4 I2C=I2C2/PD14/PD15 DA218E_INT1=%u\r\n",
               (unsigned)hw_acc_pin_high(), (unsigned)hw_acc_is_on(),
               (unsigned)work_mode_logical_acc(),
               (unsigned)GPIO_ReadInputDataBit(DA218E_INT1_PORT, DA218E_INT1_PIN));
}

static void idle_sleep_process(void)
{
    /* SysTick wakes shallow WFI every millisecond, so PA12 is polled without
     * delaying the process functions that run before this loop-tail call. */
    if (s_shallow_sleep_allowed)
        work_mode_sleep_shallow();
}

/* ═══════════════════════════════════════════════════════════════════════════
 * main
 * ═══════════════════════════════════════════════════════════════════════════ */
int main(void)
{
    /* ── 1. Core hardware init ───────────────────────────────────────────── */
    reset_diag_capture();
    reset_diag_runtime_init();
    hw_clock_init();   /* 64 MHz PLL from HSI */
    stack_paint();     /* fill unused stack with 0xAAAAAAAA for watermark */
    early_debug_uart_init();
    hw_nvic_init();
    hw_gpio_init();
    hw_usart_init();   /* USART1=debug, UART4=GPS, UART5=EC800M */
    hw_spi_init();
    hw_i2c_init();
    hw_adc_init();
    hw_tim_init();     /* TIM8 1 ms tick */
    hw_iwdg_init();
    s_iwdg_started = true;

    enable_debug_rx_irq();

    dbg_printf("\r\n========================================\r\n");
    /* Display the build stamp, not the fixed release-contract date. The
     * semantic version and OTA counter remain the release identity. */
    dbg_printf("  A300-T9 / T360-A300_406_%s,%s\r\n", FW_BUILD_NUMBER,
               strchr(FW_FULL_VERSION, ',') + 1);
    dbg_printf("  Build: %s\r\n", FW_BUILD_DATE);
    dbg_printf("  Reset: %s flags=0x%02x\r\n",
               reset_diag_name(reset_diag_reason()),
               (unsigned)reset_diag_raw_flags());
    {
        reset_diag_snapshot_t previous;
        if (reset_diag_previous(&previous) &&
            (previous.hardfault ||
             reset_diag_reason() == RESET_REASON_IWDG ||
             reset_diag_reason() == RESET_REASON_WWDG)) {
            dbg_printf("[RESET-DIAG] phase=%s seq=%lu fault=%u pc=0x%08lx lr=0x%08lx cfsr=0x%08lx hfsr=0x%08lx\r\n",
                       reset_diag_phase_name(previous.phase),
                       (unsigned long)previous.loop_sequence,
                       previous.hardfault ? 1U : 0U,
                       (unsigned long)previous.pc,
                       (unsigned long)previous.lr,
                       (unsigned long)previous.cfsr,
                       (unsigned long)previous.hfsr);
        }
    }
    dbg_printf("========================================\r\n");
    log_hardware_contract();

    /* ── 3. Flash config ─────────────────────────────────────────────────── */
    spi_flash_init();
    cfg_init();
    overspeed_policy_init(&s_overspeed_policy);
    blind_zone_init();
    device_config_t *c = cfg_get();
    dbg_printf("[CFG] server=%s:%u report=%u/%us effective_stop=%us hb=%us plate=%s\r\n",
               c->server_ip, c->server_port,
               (unsigned)c->report_moving_s,
               (unsigned)c->report_stopped_s,
               (unsigned)(c->report_stopped_s != 0U ?
                          c->report_stopped_s :
                          WORK_MODE_DEFAULT_STOPPED_REPORT_S),
               (unsigned)c->heartbeat_s, c->plate_no);

    /* ── 4. Peripheral drivers ───────────────────────────────────────────── */
    adc_monitor_init();
    geofence_init();
    agnss_init(cfg_get()->gnss_type);
    agnss_set_inject_callback(gnss_vendor_inject);
    at_config_init();
    log_platform_init();
    cfg_query_init();

    /* ── 5. Build JT808 terminal info from flash config ─────────────────── */
    memset(&s_terminal, 0, sizeof(s_terminal));
    memcpy(s_terminal.manufacturer_id, FW_MANUFACTURER_ID_STR, 5U);
    strncpy(s_terminal.terminal_model,
            c->terminal_model[0] != '\0' ? c->terminal_model : FW_JT808_MODEL_STR,
            sizeof(s_terminal.terminal_model) - 1U);
    s_terminal.terminal_model[sizeof(s_terminal.terminal_model) - 1U] = '\0';
    s_terminal.terminal_id[0] = '\0';
    strncpy(s_terminal.plate_no,       c->plate_no,    sizeof(s_terminal.plate_no) - 1);
    strncpy(s_terminal.phone,          c->phone,       sizeof(s_terminal.phone) - 1);
    strncpy(s_terminal.auth_code,      c->auth_code,   sizeof(s_terminal.auth_code) - 1);
    s_terminal.color = 1;

    /* ── 6. GPS + DA218E (independent 3.3 V sensor rail) ───────────────────── */
    gps_enable(true);
    i2c_accel_init();
    s_vibration_rearm_fault = !i2c_accel_get_diag()->int1_rearm_ok;
    gps_init();

    /* ── 7. 4G modem ─────────────────────────────────────────────────────── */
    ec800m_init();
    /* Modem initialization clears channel callbacks; bind OTA afterwards. */
    fota_init();
    ec800m_register_agnss_recv(agnss_network_rx);
    sms_set_recv_cb(sms_command_execute);

    /* ── 8. JT808 + TCP manager ──────────────────────────────────────────── */
    jt808_init(&s_terminal);
    jt808_set_server(c->server_ip, c->server_port, false);
    jt808_set_server(c->backup_ip, c->backup_port, true);
    jt808_set_heartbeat_s(c->heartbeat_s);
    jt808_set_report_interval(c->report_moving_s, c->report_stopped_s);
    tcp_manager_init();

    /* ── 9. Power manager ────────────────────────────────────────────────── */
    pwr_init();
    {
        work_mode_config_t wm_cfg = {
            c->report_moving_s, c->report_stopped_s, c->heartbeat_s,
            300U, 6U
        };
        work_mode_init(&wm_cfg, work_mode_sleep_monotonic_s(),
                       hw_acc_is_on());
        work_mode_set_stationary_location_enabled(c->sleep_report_mode == 0U,
                                                  work_mode_sleep_monotonic_s());
    }

    dbg_printf("[BOOT] ready\r\n");

    /* ── 10. Main loop ───────────────────────────────────────────────────── */
    bool cfg_query_started = false;
    while (1) {
        IWDG_ReloadKey();

        reset_diag_loop_begin();
        reset_diag_mark_phase(RESET_DIAG_PHASE_EC800M);
        ec800m_process();
        reset_diag_mark_phase(RESET_DIAG_PHASE_GPS);
        gps_process();
        reset_diag_mark_phase(RESET_DIAG_PHASE_MILEAGE);
        mileage_update();
        mileage_persist_process(TICK_MS());
        reset_diag_mark_phase(RESET_DIAG_PHASE_TCP_MANAGER);
        tcp_manager_process();
        reset_diag_mark_phase(RESET_DIAG_PHASE_JT808);
        jt808_process();
        reset_diag_mark_phase(RESET_DIAG_PHASE_ADC);
        adc_monitor_process();
        reset_diag_mark_phase(RESET_DIAG_PHASE_GEOFENCE);
        geofence_process();
        reset_diag_mark_phase(RESET_DIAG_PHASE_FOTA);
        fota_process();
        fota_confirm_trial_process();
        reset_diag_mark_phase(RESET_DIAG_PHASE_BLIND_ZONE);
        blind_zone_recovery_process();
        blind_zone_replay_process();
        reset_diag_mark_phase(RESET_DIAG_PHASE_LOG_PLATFORM);
        log_platform_process();
        if (!cfg_query_started && ec800m_is_ready() && jt808_is_online() &&
            !work_mode_sleep_is_in_stop1() && fota_get_state() == FOTA_STATE_IDLE &&
            cfg_query_start() == 0)
            cfg_query_started = true;
        reset_diag_mark_phase(RESET_DIAG_PHASE_CONFIG);
        cfg_query_process();
        reset_diag_mark_phase(RESET_DIAG_PHASE_AGNSS);
        agnss_process();
        reset_diag_mark_phase(RESET_DIAG_PHASE_WORK_MODE);
        work_mode_process();
        reset_diag_mark_phase(RESET_DIAG_PHASE_AT_CONFIG);
        at_config_process();
        reset_diag_mark_phase(RESET_DIAG_PHASE_SMS);
        sms_process();
        reset_diag_mark_phase(RESET_DIAG_PHASE_ALARMS);
        scan_alarms();
        reset_diag_mark_phase(RESET_DIAG_PHASE_NTP);
        ntp_resync_process();
        reset_diag_mark_phase(RESET_DIAG_PHASE_STATUS);
        periodic_status_log();

        reset_diag_mark_phase(RESET_DIAG_PHASE_IDLE_SLEEP);
        idle_sleep_process();
    }
}
