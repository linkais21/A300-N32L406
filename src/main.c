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
#include "n32l40x.h"
#include <string.h>

/* ── Terminal info loaded from flash at runtime ───────────────────────────── */
static jt808_terminal_t s_terminal;
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

static void early_uart_raw_puts(const char *s)
{
    uint32_t guard;
    while (*s) {
        guard = 100000U;
        while (USART_GetFlagStatus(DBG_UART, USART_FLAG_TXDE) == RESET && guard-- != 0U) {
        }
        if (guard == 0U) return;
        USART_SendData(DBG_UART, (uint8_t)*s++);
    }
    guard = 100000U;
    while (USART_GetFlagStatus(DBG_UART, USART_FLAG_TXC) == RESET && guard-- != 0U) {
    }
}

void HardFault_Handler(void)
{
    early_debug_uart_init();
    early_uart_raw_puts("\r\n[FAULT] HardFault\r\n");
    while (1) {
    }
}

/* ── TIM8 update interrupt: 1 ms tick ────────────────────────────────────── */
void TIM8_UP_IRQHandler(void)
{
    if (TIM_GetIntStatus(TIM8, TIM_INT_UPDATE))
        TIM_ClrIntPendingBit(TIM8, TIM_INT_UPDATE);
}

/* EC800M RX is now handled by UART5_IRQHandler() inside ec800m.c.
 * (DMA receive was removed — it never delivered modem data reliably.) */

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

/* ── Periodic log: every 5 s print status ───────────────────────────────── */
#define RAM_STATIC  ((uint32_t)(&_ebss) - 0x20000000u)  /* data+bss, compile-time constant */
#define RAM_TOTAL   (24u * 1024u)
#define RAM_AVAIL   (RAM_TOTAL - RAM_STATIC)             /* bytes shared by heap and stack */
#define STACK_MARGIN_MIN (4u * 1024u)
static volatile uint32_t s_stack_margin_fault;
static volatile bool s_work_vibration_hit;

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
    dbg_printf("[GPS] RX=%lu SENT=%lu GGA=%lu RMC=%lu OK=%lu CS=%lu FMT=%lu NOFIX=%lu DROP=%lu\r\n",
               (unsigned long)gps_diag->rx_bytes,
               (unsigned long)gps_diag->sentences,
               (unsigned long)gps_diag->gga,
               (unsigned long)gps_diag->rmc,
               (unsigned long)gps_diag->parsed,
               (unsigned long)gps_diag->checksum_fail,
               (unsigned long)gps_diag->format_fail,
               (unsigned long)gps_diag->no_fix,
               (unsigned long)gps_diag->drop);
    dbg_printf("[ACCEL] addr=0x%02x INT1=%u X=%d Y=%d Z=%d read_ok=%u samples=%lu fails=%lu delta=%u threshold=%u hits=%lu\r\n",
               accel_diag->address,
               (unsigned)GPIO_ReadInputDataBit(DA218E_INT1_PORT, DA218E_INT1_PIN),
               accel_diag->x, accel_diag->y, accel_diag->z,
               (unsigned)accel_diag->read_ok,
               (unsigned long)accel_diag->sample_count,
               (unsigned long)accel_diag->read_fail_count,
               (unsigned)accel_diag->delta, (unsigned)accel_diag->threshold,
               (unsigned long)accel_diag->vibration_hit_count);
    dbg_printf("[WORK] state=%s pin_high=%u acc_on=%u logical_acc=%u vib=%u stop=%u now=%lu\r\n",
               work_mode_state_name(work_mode_state()),
               (unsigned)hw_acc_pin_high(),
               (unsigned)hw_acc_is_on(),
               (unsigned)work_mode_logical_acc(),
               (unsigned)s_work_vibration_hit,
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
    bool vibration_wake_hold;
    uint8_t processed = 0U;
    uint32_t now_s = work_mode_sleep_monotonic_s();
    if (wake != WORK_SLEEP_WAKE_NONE) {
        /* STOP1 suspends SysTick; make the first post-wake accelerometer
         * sample eligible before work-mode evaluates the wake window. */
        i2c_accel_prepare_wake_sampling();
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
    /* The PB3 interrupt is the first evidence of a vibration wake. Count the
     * wake sample itself so the six-second confirmation starts immediately,
     * rather than waiting for a second I2C sample after WFI returns. */
    if ((wake & WORK_SLEEP_WAKE_VIBRATION) != 0U) {
        input.vibration_sample_valid = true;
        input.vibration_hit = true;
    }
    if ((wake & WORK_SLEEP_WAKE_VIBRATION) != 0U) {
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
    if (work_mode_state() == WORK_MODE_REALTIME ||
        !vibration_wake_hold) {
        vibration_wake_window = false;
        vibration_wake_hold = false;
    }
    s_work_vibration_hit = input.vibration_hit;
    input.rtc_wake = (wake & WORK_SLEEP_WAKE_RTC) != 0U;
    input.alarm_bits = work_mode_take_alarm();
    input.gps_valid = gps_get_data()->valid;
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

    if (work_mode_state() != last_state) {
        dbg_printf("[WORK] transition %s->%s now=%lu pin_high=%u acc_on=%u logical_acc=%u vib=%u\r\n",
                   work_mode_state_name(last_state),
                   work_mode_state_name(work_mode_state()),
                   (unsigned long)now_s, (unsigned)hw_acc_pin_high(),
                   (unsigned)input.acc_high,
                   (unsigned)work_mode_logical_acc(),
                   (unsigned)input.vibration_hit);
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
            gps_enable(true);
            gps_resume_after_wake();
            break;
        case WORK_ACTION_GPS_OFF:
            (void)gps_capture_last_trusted();
            gps_enable(false);
            break;
        case WORK_ACTION_REPORT_ENTRY:
        case WORK_ACTION_REPORT_LOCATION:
        case WORK_ACTION_REPORT_ALARM:
            if (jt808_send_location_work_mode(action.alarm_bits,
                                               action.historical_position) != 0)
                work_mode_retry_action(&action);
            break;
        case WORK_ACTION_REPORT_HEARTBEAT:
            if (jt808_send_heartbeat() != 0)
                work_mode_retry_action(&action);
            break;
        case WORK_ACTION_ENTER_STOP1:
            /* `wake` has already been consumed above.  Passing it again as a
             * pending wake aborts STOP1 admission and can leave the unit in
             * GPS-off SLEEP forever (especially after a vibration wake). */
            work_mode_sleep_process(15000U, WORK_SLEEP_WAKE_NONE);
            wake = WORK_SLEEP_WAKE_NONE;
            break;
        default:
            break;
        }
    }

    if (work_mode_state() == WORK_MODE_STATIONARY_SLEEP &&
        !vibration_wake_hold &&
        !work_mode_sleep_is_in_stop1()) {
        work_mode_sleep_process(15000U, wake);
    }
}

static void log_hardware_contract(void)
{
    dbg_printf("[HW] ACC=PA12 pin_high=%u acc_on=%u logical_acc=%u CAR_ADC=PA3/CH4 I2C=I2C2/PD14/PD15 DA218E_INT1=%u\r\n",
               (unsigned)hw_acc_pin_high(), (unsigned)hw_acc_is_on(),
               (unsigned)work_mode_logical_acc(),
               (unsigned)GPIO_ReadInputDataBit(DA218E_INT1_PORT, DA218E_INT1_PIN));
}

/* ═══════════════════════════════════════════════════════════════════════════
 * main
 * ═══════════════════════════════════════════════════════════════════════════ */
int main(void)
{
    /* ── 1. Core hardware init ───────────────────────────────────────────── */
    reset_diag_capture();
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

    enable_debug_rx_irq();

    dbg_printf("\r\n========================================\r\n");
    dbg_printf("  A300-T9 / %s\r\n", FW_FULL_VERSION);
    dbg_printf("  Build: %s\r\n", FW_BUILD_DATE);
    dbg_printf("  Reset: %s\r\n", reset_diag_name(reset_diag_reason()));
    dbg_printf("========================================\r\n");
    log_hardware_contract();

    /* ── 3. Flash config ─────────────────────────────────────────────────── */
    spi_flash_init();
    cfg_init();
    blind_zone_init();
    device_config_t *c = cfg_get();
    dbg_printf("[CFG] server=%s:%u hb=%us plate=%s\r\n",
               c->server_ip, c->server_port, c->heartbeat_s, c->plate_no);

    /* ── 4. Peripheral drivers ───────────────────────────────────────────── */
    adc_monitor_init();
    geofence_init();
    fota_init();
    agnss_init(cfg_get()->gnss_type);
    agnss_set_inject_callback(gnss_vendor_inject);
    at_config_init();
    log_platform_init();
    cfg_query_init();

    /* ── 5. Build JT808 terminal info from flash config ─────────────────── */
    memset(&s_terminal, 0, sizeof(s_terminal));
    memcpy(s_terminal.manufacturer_id, "CYHLL", 5);
    memcpy(s_terminal.terminal_model, FW_MODEL_STR,
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
    gps_init();

    /* ── 7. 4G modem ─────────────────────────────────────────────────────── */
    ec800m_init();
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
    }

    dbg_printf("[BOOT] ready\r\n");

    /* ── 10. Main loop ───────────────────────────────────────────────────── */
    bool cfg_query_started = false;
    while (1) {
        IWDG_ReloadKey();

        ec800m_process();
        gps_process();
        mileage_update();
        tcp_manager_process();
        jt808_process();
        adc_monitor_process();
        geofence_process();
        fota_process();
        fota_confirm_trial_process();
        blind_zone_recovery_process();
        blind_zone_replay_process();
        log_platform_process();
        if (!cfg_query_started && ec800m_is_ready() && jt808_is_online() &&
            !work_mode_sleep_is_in_stop1() && fota_get_state() == FOTA_STATE_IDLE &&
            cfg_query_start() == 0)
            cfg_query_started = true;
        cfg_query_process();
        agnss_process();
        work_mode_process();
        at_config_process();
        sms_process();
        scan_alarms();
        ntp_resync_process();
        periodic_status_log();
    }
}
