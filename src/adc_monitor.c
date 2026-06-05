#include "adc_monitor.h"
#include "config.h"
#include "hw_init.h"
#include "jt808.h"
#include "n32l40x.h"

static float s_car_v = 0.0f;
static float s_bat_v = 0.0f;
static uint32_t s_last_ms = 0;

static float adc_read_ch(uint8_t ch)
{
    ADC_ConfigRegularChannel(ADC, ch, 1, ADC_SAMP_TIME_55CYCLES5);
    ADC_EnableSoftwareStartConv(ADC, ENABLE);
    uint32_t t = TICK_MS();
    while (!ADC_GetFlagStatus(ADC, ADC_FLAG_ENDC)) {
        if (TICK_MS() - t > 10) return 0.0f;
    }
    uint16_t raw = ADC_GetDat(ADC);
    ADC_ClearFlag(ADC, ADC_FLAG_ENDC);
    return (raw / 4095.0f) * 3.3f;
}

void adc_monitor_init(void) { s_last_ms = 0; }

void adc_monitor_process(void)
{
    if (TICK_MS() - s_last_ms < 1000) return;
    s_last_ms = TICK_MS();

    float prev_car = s_car_v;
    s_car_v = adc_read_ch(ADC_CAR_CH) * ADC_CAR_RATIO;
    s_bat_v = adc_read_ch(ADC_BAT_CH) * ADC_BAT_RATIO;

    /* Power cut: car voltage drops from >9 V to <4 V */
    if (prev_car > 9.0f && s_car_v < 4.0f)
        jt808_trigger_alarm(ALM_POWER_CUT);

    if (adc_is_bat_low())
        jt808_trigger_alarm(ALM_POWER_LOW);
}

float adc_get_car_voltage(void) { return s_car_v; }
float adc_get_bat_voltage(void) { return s_bat_v; }
bool  adc_is_car_powered(void)  { return s_car_v > 9.0f; }
bool  adc_is_bat_low(void)      { return s_bat_v < 3.5f && s_bat_v > 0.5f; }
