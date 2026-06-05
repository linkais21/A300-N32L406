#include "power_mgr.h"
#include "ec800m.h"
#include "gps.h"
#include "jt808.h"
#include "adc_monitor.h"
#include "flash_config.h"
#include "debug_uart.h"
#include "hw_init.h"
#include "config.h"
#include "n32l40x.h"
#include <string.h>

/*
 * Power states and transitions:
 *
 *  ACTIVE ──(no ACC, no movement, timeout)──► IDLE
 *  IDLE   ──(RTC period expired)───────────► SLEEP
 *  SLEEP  ──(long idle)────────────────────► DEEP_SLEEP
 *  any    ──(wake source)──────────────────► ACTIVE
 *
 * ACTIVE:      GPS on, 4G on, reporting running
 * IDLE:        GPS off, 4G connected (heartbeat only), no location
 * SLEEP:       GPS off, EC800M AT+QSCLK=1 (PSM), MCU WFI
 * DEEP_SLEEP:  GPS off, EC800M AT+QPOWD=0, MCU STOP mode, only RTC/EXTI wake
 */

#define IDLE_TIMEOUT_S       120   /* no ACC + no movement → IDLE after this */
#define SLEEP_TIMEOUT_S      300   /* IDLE with no wake → SLEEP after this   */
#define DEEP_SLEEP_TIMEOUT_S 600   /* SLEEP with no wake → DEEP_SLEEP        */
#define RTC_WAKE_INTERVAL_S  30    /* periodic wake in SLEEP to send heartbeat */

static pwr_state_t s_state        = PWR_STATE_ACTIVE;
static uint32_t    s_state_ms     = 0;
static volatile wake_src_t s_wake = WAKE_SRC_NONE;

/* ── EXTI config for wake pins ────────────────────────────────────────────── */
static void exti_setup(GPIO_Module *port, uint16_t pin, uint8_t port_src,
                        uint8_t pin_src, EXTI_TriggerType trig, IRQn_Type irqn)
{
    EXTI_InitType e;
    GPIO_ConfigEXTILine(port_src, pin_src);
    EXTI_InitStruct(&e);
    e.EXTI_Line    = (uint32_t)(1u << pin_src);
    e.EXTI_Mode    = EXTI_Mode_Interrupt;
    e.EXTI_Trigger = trig;
    e.EXTI_LineCmd = ENABLE;
    EXTI_InitPeripheral(&e);

    NVIC_InitType n;
    n.NVIC_IRQChannel                   = irqn;
    n.NVIC_IRQChannelPreemptionPriority = 0;
    n.NVIC_IRQChannelSubPriority        = 0;
    n.NVIC_IRQChannelCmd                = ENABLE;
    NVIC_Init(&n);
    (void)port; (void)pin;
}

void pwr_init(void)
{
    RCC_EnableAPB2PeriphClk(RCC_APB2_PERIPH_AFIO, ENABLE);

    /* ACC detect: PA3/PA12 falling edge (ignition off) */
    exti_setup(ACC_DET_PORT, ACC_DET_PIN,
               GPIOA_PORT_SOURCE, GPIO_PIN_SOURCE3,
               EXTI_Trigger_Falling, EXTI3_IRQn);

    /* SOS button: PA4 falling edge */
    exti_setup(SOS_PORT, SOS_PIN,
               GPIOA_PORT_SOURCE, GPIO_PIN_SOURCE4,
               EXTI_Trigger_Falling, EXTI4_IRQn);

    /* Light sensor: PB0 rising edge */
    exti_setup(LIGHT_INT_PORT, LIGHT_INT_PIN,
               GPIOB_PORT_SOURCE, GPIO_PIN_SOURCE0,
               EXTI_Trigger_Rising, EXTI0_IRQn);

    /* DC_UP (charge detect): PA8 both edges */
    exti_setup(DC_UP_PORT, DC_UP_PIN,
               GPIOA_PORT_SOURCE, GPIO_PIN_SOURCE8,
               EXTI_Trigger_Rising_Falling, EXTI9_5_IRQn);

    s_state    = PWR_STATE_ACTIVE;
    s_state_ms = TICK_MS();
    dbg_printf("[PWR] init, state=ACTIVE\r\n");
}

/* ── Enter/exit state helpers ─────────────────────────────────────────────── */
/* Forward declaration */
static void enter_active(void);

static void enter_idle(void)
{
    dbg_printf("[PWR] → IDLE\r\n");
    gps_enable(false);
    /* Keep 4G alive for heartbeat; just reduce report frequency */
    s_state    = PWR_STATE_IDLE;
    s_state_ms = TICK_MS();
}

static void enter_sleep(void)
{
    dbg_printf("[PWR] → SLEEP (EC800M PSM)\r\n");
    ec800m_sleep_enable();
    s_state    = PWR_STATE_SLEEP;
    s_state_ms = TICK_MS();
}

static void enter_deep_sleep(void)
{
    dbg_printf("[PWR] → DEEP_SLEEP (EC800M off, MCU STOP)\r\n");
    ec800m_power_off();

    /* MCU low-power sleep — wake on any EXTI/IRQ */
    PWR_EnterSLEEPMode(0, PWR_STOPENTRY_WFI);

    /* Execution resumes here after wake interrupt */
    dbg_printf("[PWR] woke from DEEP_SLEEP\r\n");
    enter_active();
}

static void enter_active(void)
{
    dbg_printf("[PWR] → ACTIVE (wake src=0x%x)\r\n", (unsigned)s_wake);
    s_wake = WAKE_SRC_NONE;

    gps_enable(true);

    if (ec800m_get_state() == EC800M_STATE_OFF) {
        ec800m_init();
    } else {
        ec800m_sleep_disable();
    }

    s_state    = PWR_STATE_ACTIVE;
    s_state_ms = TICK_MS();
}

/* ── Main process ─────────────────────────────────────────────────────────── */
void pwr_process(void)
{
    uint32_t elapsed_s = (TICK_MS() - s_state_ms) / 1000;

    /* Any pending wake source → back to ACTIVE */
    if (s_wake != WAKE_SRC_NONE && s_state != PWR_STATE_ACTIVE) {
        enter_active();
        return;
    }

    switch (s_state) {
    case PWR_STATE_ACTIVE: {
        /* Check if we should idle: no ACC and no motion */
        bool acc_on   = (GPIO_ReadInputDataBit(ACC_DET_PORT, ACC_DET_PIN) == Bit_SET);
        bool car_on   = adc_is_car_powered();
        bool moving   = (gps_get_data()->speed_kmh > 2.0f);

        if (!acc_on && !car_on && !moving && elapsed_s > IDLE_TIMEOUT_S)
            enter_idle();
        break;
    }
    case PWR_STATE_IDLE:
        if (elapsed_s > SLEEP_TIMEOUT_S)
            enter_sleep();
        else {
            /* While idle, still send periodic JT808 heartbeat */
            static uint32_t last_hb = 0;
            if (TICK_MS() - last_hb > 60000) {
                jt808_send_heartbeat();
                last_hb = TICK_MS();
            }
        }
        break;

    case PWR_STATE_SLEEP:
        if (elapsed_s > DEEP_SLEEP_TIMEOUT_S)
            enter_deep_sleep();
        break;

    case PWR_STATE_DEEP_SLEEP:
        /* Handled inside enter_deep_sleep() via WFI */
        break;
    }
}

pwr_state_t pwr_get_state(void) { return s_state; }

void pwr_request_sleep(void)
{
    if (s_state == PWR_STATE_ACTIVE) enter_idle();
}

void pwr_wake(wake_src_t src)
{
    s_wake |= src;
}

/* ── EXTI ISR handlers ────────────────────────────────────────────────────── */
void pwr_vibration_isr(void)  { pwr_wake(WAKE_SRC_VIBRATION); }
void pwr_acc_isr(void)        { pwr_wake(WAKE_SRC_ACC); }
void pwr_sos_isr(void)        { pwr_wake(WAKE_SRC_SOS); }
void pwr_charge_isr(void)     { pwr_wake(WAKE_SRC_CHARGE); }
void pwr_light_isr(void)      { pwr_wake(WAKE_SRC_LIGHT); }

/* ── Actual IRQ handlers (routed through pwr_*_isr) ──────────────────────── */
void EXTI0_IRQHandler(void)   /* PB0 light */
{
    if (EXTI_GetITStatus(EXTI_LINE0)) {
        EXTI_ClrITPendBit(EXTI_LINE0);
        pwr_light_isr();
    }
}
void EXTI3_IRQHandler(void)   /* PA3 ACC */
{
    if (EXTI_GetITStatus(EXTI_LINE3)) {
        EXTI_ClrITPendBit(EXTI_LINE3);
        pwr_acc_isr();
    }
}
void EXTI4_IRQHandler(void)   /* PA4 SOS */
{
    if (EXTI_GetITStatus(EXTI_LINE4)) {
        EXTI_ClrITPendBit(EXTI_LINE4);
        pwr_sos_isr();
        jt808_trigger_alarm(ALM_EMERGENCY_SOS);
    }
}
void EXTI9_5_IRQHandler(void) /* PA8 charge detect */
{
    if (EXTI_GetITStatus(EXTI_LINE8)) {
        EXTI_ClrITPendBit(EXTI_LINE8);
        pwr_charge_isr();
    }
}
