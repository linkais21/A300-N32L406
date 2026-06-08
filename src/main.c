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
    while (*s) {
        while (USART_GetFlagStatus(DBG_UART, USART_FLAG_TXDE) == RESET);
        USART_SendData(DBG_UART, (uint8_t)*s++);
    }
    while (USART_GetFlagStatus(DBG_UART, USART_FLAG_TXC) == RESET);
}

void HardFault_Handler(void)
{
    early_debug_uart_init();
    early_uart_raw_puts("\r\n[FAULT] HardFault\r\n");
    while (1) {
    }
}

/* ── TIM8 update interrupt: 1 ms LED blink ───────────────────────────────── */
void TIM8_UP_IRQHandler(void)
{
    if (TIM_GetIntStatus(TIM8, TIM_INT_UPDATE)) {
        TIM_ClrIntPendingBit(TIM8, TIM_INT_UPDATE);

        static uint16_t led_cnt = 0;
        if (++led_cnt >= 500) {
            led_cnt = 0;
            /* GPS LED: solid while searching, 1 Hz blink when fixed */
            if (gps_is_valid()) {
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

    /* Bring USART1 (debug) up FIRST, before nvic/gpio/everything else, so we
     * can trace each init step. Needs GPIOA clock + USART1 clock only. */
    early_debug_uart_init();
    hw_nvic_init();
    hw_gpio_init();
    hw_usart_init();   /* USART1=debug(PA9/PA10), USART2=GPS, UART5=EC800M(PB4/PB5) */
    hw_spi_init();
    hw_i2c_init();
    hw_adc_init();
    hw_tim_init();     /* TIM8 1 ms tick */
    hw_iwdg_init();

    enable_debug_rx_irq();

    dbg_printf("\r\n========================================\r\n");
    dbg_printf("  A300-T9 / %s\r\n", FW_FULL_VERSION);
    dbg_printf("  Build: %s\r\n", FW_BUILD_DATE);
    dbg_printf("========================================\r\n");

    /* ── 3. Flash config ─────────────────────────────────────────────────── */
    spi_flash_init();
    cfg_init();
    device_config_t *c = cfg_get();
    dbg_printf("[CFG] server=%s:%u hb=%us plate=%s\r\n",
               c->server_ip, c->server_port, c->heartbeat_s, c->plate_no);

    /* ── 4. Peripheral drivers ───────────────────────────────────────────── */
    i2c_accel_init();
    adc_monitor_init();
    geofence_init();
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
    gps_enable(true);
    gps_init();

    /* ── 7. 4G modem ─────────────────────────────────────────────────────── */
    ec800m_init();

    /* ── 8. JT808 + TCP manager ──────────────────────────────────────────── */
    jt808_init(&s_terminal);
    jt808_set_server(c->server_ip, c->server_port, false);
    jt808_set_server(c->backup_ip[0] ? c->backup_ip : c->server_ip,
                     c->backup_port  ? c->backup_port : c->server_port, true);
    tcp_manager_init();

    /* ── 9. Power manager ────────────────────────────────────────────────── */
    pwr_init();

    dbg_printf("[BOOT] ready\r\n");

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
