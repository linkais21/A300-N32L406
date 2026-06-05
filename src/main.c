#include "config.h"
#include "hw_init.h"
#include "debug_uart.h"
#include "ec800m.h"
#include "gps.h"
#include "jt808.h"
#include "at_config.h"
#include "adc_monitor.h"
#include "spi_flash.h"
#include "i2c_accel.h"
#include "relay.h"
#include "flash_config.h"
#include "tcp_manager.h"
#include "power_mgr.h"
#include "mileage.h"
#include "geofence.h"
#include "fota.h"
#include "n32l40x.h"
#include <string.h>

/* ── Terminal info loaded from flash at runtime ───────────────────────────── */
static jt808_terminal_t s_terminal;

/* ── TIM8 update interrupt: 1 ms LED blink ───────────────────────────────── */
void TIM8_UP_IRQHandler(void)
{
    if (TIM_GetIntStatus(TIM8, TIM_INT_UPDATE)) {
        TIM_ClrIntPendingBit(TIM8, TIM_INT_UPDATE);

        static uint16_t led_cnt = 0;
        if (++led_cnt >= 500) {
            led_cnt = 0;
            /* GPS LED: blink 1 Hz when searching, solid when fixed */
            if (!gps_is_valid()) {
                uint8_t cur = GPIO_ReadOutputDataBit(GPS_LED_PORT, GPS_LED_PIN);
                if (cur) GPIO_ResetBits(GPS_LED_PORT, GPS_LED_PIN);
                else     GPIO_SetBits(GPS_LED_PORT, GPS_LED_PIN);
            } else {
                GPIO_SetBits(GPS_LED_PORT, GPS_LED_PIN);
            }
        }
    }
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

/* ── Periodic log: every 5 s print status ───────────────────────────────── */
static void periodic_status_log(void)
{
    static uint32_t last_ms = 0;
    if (TICK_MS() - last_ms < 5000) return;
    last_ms = TICK_MS();

    const gps_data_t *g = gps_get_data();
    float vcar = adc_get_car_voltage();
    float vbat = adc_get_bat_voltage();

    dbg_printf("[STATUS] t=%us 4G=%s GPS=%s lat=%.6f lon=%.6f spd=%.1f "
               "vcar=%.1fV vbat=%.2fV csq=%d\r\n",
               (unsigned)(TICK_MS() / 1000),
               ec800m_is_ready()  ? "RDY" : "---",
               g->valid           ? "FIX" : "SRH",
               g->lat, g->lon, g->speed_kmh,
               vcar, vbat,
               ec800m_get_csq());
}

/* ── Alarm scanning ──────────────────────────────────────────────────────── */
static void scan_alarms(void)
{
    static uint32_t last_vib_ms = 0;
    if (TICK_MS() - last_vib_ms > 200) {
        last_vib_ms = TICK_MS();
        if (i2c_accel_detect_vibration())
            jt808_trigger_alarm(ALM_VIBRATION);
    }

    static bool sos_prev = false;
    bool sos_now = (GPIO_ReadInputDataBit(SOS_PORT, SOS_PIN) == Bit_RESET);
    if (sos_now && !sos_prev) {
        dbg_printf("[ALARM] SOS pressed\r\n");
        jt808_trigger_alarm(ALM_EMERGENCY_SOS);
    }
    sos_prev = sos_now;

    /* Power cut: car voltage absent while previously present */
    static bool car_prev = false;
    bool car_now = adc_is_car_powered();
    if (car_prev && !car_now) {
        dbg_printf("[ALARM] power cut detected\r\n");
        jt808_trigger_alarm(ALM_POWER_CUT);
    }
    car_prev = car_now;
}

/* ═══════════════════════════════════════════════════════════════════════════
 * main
 * ═══════════════════════════════════════════════════════════════════════════ */
int main(void)
{
    /* ── 1. Core hardware init ───────────────────────────────────────────── */
    hw_clock_init();   /* 64 MHz PLL from HSI */
    hw_nvic_init();
    hw_gpio_init();
    hw_usart_init();   /* USART1=debug(PA9/PA10), USART2=GPS, UART5=EC800M */
    hw_spi_init();
    hw_i2c_init();
    hw_adc_init();
    hw_tim_init();     /* TIM8 1 ms tick */
    hw_iwdg_init();

    enable_debug_rx_irq();

    /* ── 2. First log output — confirms UART is alive ────────────────────── */
    dbg_printf("\r\n");
    dbg_printf("========================================\r\n");
    dbg_printf("  A300-T9 / %s\r\n", FW_VERSION_STR);
    dbg_printf("  Build: " __DATE__ " " __TIME__ "\r\n");
    dbg_printf("  DEBUG UART: PA9(TX) PA10(RX) 115200\r\n");
    dbg_printf("========================================\r\n");

    /* ── 3. Flash config ─────────────────────────────────────────────────── */
    dbg_printf("[INIT] loading flash config...\r\n");
    spi_flash_init();
    cfg_init();   /* load or apply defaults */
    device_config_t *c = cfg_get();
    dbg_printf("[CFG]  server=%s:%u  hb=%us  moving=%us  stopped=%us\r\n",
               c->server_ip, c->server_port,
               c->heartbeat_s, c->report_moving_s, c->report_stopped_s);
    dbg_printf("[CFG]  mileage=%u m  plate=%s\r\n",
               (unsigned)c->mileage_m, c->plate_no);

    /* ── 4. Peripheral drivers ───────────────────────────────────────────── */
    dbg_printf("[INIT] accelerometer...\r\n");
    i2c_accel_init();

    dbg_printf("[INIT] ADC monitor...\r\n");
    adc_monitor_init();

    dbg_printf("[INIT] geofence...\r\n");
    geofence_init();

    dbg_printf("[INIT] FOTA...\r\n");
    fota_init();

    at_config_init();

    /* ── 5. Build JT808 terminal info from flash config ─────────────────── */
    memset(&s_terminal, 0, sizeof(s_terminal));
    memcpy(s_terminal.manufacturer_id, "CYHLL", 5);
    strncpy(s_terminal.terminal_model, FW_MODEL_STR,   sizeof(s_terminal.terminal_model) - 1);
    strncpy(s_terminal.terminal_id,    "T663B01",      sizeof(s_terminal.terminal_id) - 1);
    strncpy(s_terminal.plate_no,       c->plate_no,    sizeof(s_terminal.plate_no) - 1);
    strncpy(s_terminal.phone,          c->phone,       sizeof(s_terminal.phone) - 1);
    strncpy(s_terminal.auth_code,      c->auth_code,   sizeof(s_terminal.auth_code) - 1);
    s_terminal.color = 1;

    /* ── 6. GPS ──────────────────────────────────────────────────────────── */
    dbg_printf("[INIT] GPS (TAU804M) power on...\r\n");
    gps_enable(true);
    gps_init();

    /* ── 7. 4G modem ─────────────────────────────────────────────────────── */
    dbg_printf("[INIT] EC800M power on...\r\n");
    ec800m_init();

    /* ── 8. JT808 + TCP manager ──────────────────────────────────────────── */
    dbg_printf("[INIT] JT808 init  server=%s:%u\r\n",
               c->server_ip, c->server_port);
    jt808_init(&s_terminal);
    tcp_manager_init();

    /* ── 9. Power manager ────────────────────────────────────────────────── */
    dbg_printf("[INIT] power manager...\r\n");
    pwr_init();

    dbg_printf("[INIT] all done - entering main loop\r\n");
    dbg_printf("  Type commands via UART (e.g. CHECK, VERSION, POSITION)\r\n");
    dbg_printf("----------------------------------------\r\n");

    /* ── 10. Main loop ───────────────────────────────────────────────────── */
    while (1) {
        IWDG_ReloadKey();

        ec800m_process();
        gps_process();
        mileage_update();
        jt808_process();
        tcp_manager_process();
        adc_monitor_process();
        geofence_process();
        fota_process();
        pwr_process();
        at_config_process();
        scan_alarms();
        periodic_status_log();
    }
}
