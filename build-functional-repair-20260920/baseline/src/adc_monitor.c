#include "adc_monitor.h"
#include "config.h"
#include "hw_init.h"
#include "jt808.h"
#include "mileage.h"
#include "n32l40x.h"

static float s_car_v = 0.0f;
static float s_bat_v = 0.0f;
static uint32_t s_last_ms = 0;
static bool s_valid;

static float adc_read_ch(uint8_t ch)
{
    ADC_ConfigRegularChannel(ADC, ch, 1, ADC_SAMP_TIME_55CYCLES5);
    ADC_ClearFlag(ADC, ADC_FLAG_ENDC);
    ADC_EnableSoftwareStartConv(ADC, ENABLE);
    uint32_t t = TICK_MS();
    while (!ADC_GetFlagStatus(ADC, ADC_FLAG_ENDC)) {
        if (TICK_MS() - t > 10) return -1.0f;
    }
    uint16_t raw = ADC_GetDat(ADC);
    ADC_ClearFlag(ADC, ADC_FLAG_ENDC);
    return (raw / 4095.0f) * 3.3f;
}

void adc_monitor_init(void) { s_last_ms = 0; s_valid = false; }
bool adc_monitor_valid(void)
{
    return s_valid && (uint32_t)(TICK_MS() - s_last_ms) <= 2000U;
}

void adc_monitor_process(void)
{
    if (TICK_MS() - s_last_ms < 1000) return;
    s_last_ms = TICK_MS();

    float prev_car = s_car_v;
    float car = adc_read_ch(ADC_CAR_CH);
    float bat = adc_read_ch(ADC_BAT_CH);
    s_valid = car >= 0.0f && bat >= 0.0f;
    /* Production status requires both channels, but an unrelated channel
     * failure must not suppress a valid power-cut edge or mileage flush. */
    if (car >= 0.0f) s_car_v = car * ADC_CAR_RATIO;
    if (bat >= 0.0f) s_bat_v = bat * ADC_BAT_RATIO;

    /* Power cut: car voltage drops from >9 V to <4 V */
    if (prev_car > 9.0f && s_car_v < 4.0f) {
        jt808_trigger_alarm(ALM_POWER_CUT);
        (void)mileage_force_save(TICK_MS());
    }

    if (bat >= 0.0f && adc_is_bat_low())
        jt808_trigger_alarm(ALM_POWER_LOW);
}

float adc_get_car_voltage(void) { return s_car_v; }
float adc_get_bat_voltage(void) { return s_bat_v; }
bool  adc_is_car_powered(void)  { return s_car_v > 9.0f; }
bool  adc_is_bat_low(void)      { return s_bat_v < 3.5f && s_bat_v > 0.5f; }
