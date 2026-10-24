#!/usr/bin/env python3
"""Host regression for mileage flushes on real adc_monitor power-cut edges."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]

HARNESS = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#include "adc_monitor.h"
#include "config.h"
#include "jt808.h"

static uint32_t now_ms;
static uint8_t selected_channel;
static uint16_t car_raw;
static uint16_t bat_raw = 4095U;
static unsigned power_cut_alarms;
static unsigned power_low_alarms;
static unsigned force_saves;

uint32_t host_tick_ms(void) { return now_ms; }
void ADC_ConfigRegularChannel(void *adc, uint8_t channel, int rank, int sample)
{ (void)adc; (void)rank; (void)sample; selected_channel = channel; }
void ADC_EnableSoftwareStartConv(void *adc, int enable)
{ (void)adc; (void)enable; }
int ADC_GetFlagStatus(void *adc, uint32_t flag)
{ (void)adc; (void)flag; return 1; }
uint16_t ADC_GetDat(void *adc)
{ (void)adc; return selected_channel == ADC_CAR_CH ? car_raw : bat_raw; }
void ADC_ClearFlag(void *adc, uint32_t flag) { (void)adc; (void)flag; }
void jt808_trigger_alarm(uint32_t alarm)
{
    if (alarm == ALM_POWER_CUT) ++power_cut_alarms;
    if (alarm == ALM_POWER_LOW) ++power_low_alarms;
}
bool mileage_force_save(uint32_t at_ms)
{ assert(at_ms == now_ms); ++force_saves; return false; }

static uint16_t raw_for_car_voltage(float volts)
{
    return (uint16_t)(volts * 4095.0f / (3.3f * ADC_CAR_RATIO));
}

static void sample(uint32_t at_ms, float car_volts)
{
    now_ms = at_ms;
    car_raw = raw_for_car_voltage(car_volts);
    adc_monitor_process();
}

int main(void)
{
    adc_monitor_init();
    sample(1000U, 10.5f);
    sample(2000U, 10.2f);
    assert(power_cut_alarms == 0U && force_saves == 0U);

    sample(3000U, 3.0f);
    assert(power_cut_alarms == 1U && force_saves == 1U);
    sample(4000U, 2.5f);
    assert(power_cut_alarms == 1U && force_saves == 1U);

    sample(5000U, 10.8f);
    sample(6000U, 3.5f);
    assert(power_cut_alarms == 2U && force_saves == 2U);
    assert(power_low_alarms == 0U);
    puts("test_adc_power_loss_mileage: PASS");
    return 0;
}
'''

HEADERS = {
    "config.h": r'''#ifndef CONFIG_H
#define CONFIG_H
#define ADC_CAR_CH 0U
#define ADC_BAT_CH 1U
#define ADC_CAR_RATIO 4.0f
#define ADC_BAT_RATIO 2.0f
#endif
''',
    "hw_init.h": r'''#ifndef HW_INIT_H
#define HW_INIT_H
#include <stdint.h>
uint32_t host_tick_ms(void);
#define TICK_MS() host_tick_ms()
#endif
''',
    "jt808.h": r'''#ifndef JT808_H
#define JT808_H
#include <stdint.h>
#define ALM_POWER_CUT 0x01U
#define ALM_POWER_LOW 0x02U
void jt808_trigger_alarm(uint32_t alarm);
#endif
''',
    "mileage.h": r'''#ifndef MILEAGE_H
#define MILEAGE_H
#include <stdbool.h>
#include <stdint.h>
bool mileage_force_save(uint32_t now_ms);
#endif
''',
    "n32l40x.h": r'''#ifndef N32L40X_H
#define N32L40X_H
#include <stdint.h>
#define ADC ((void *)1)
#define ADC_SAMP_TIME_55CYCLES5 1
#define ADC_FLAG_ENDC 1U
#define ENABLE 1
void ADC_ConfigRegularChannel(void *, uint8_t, int, int);
void ADC_EnableSoftwareStartConv(void *, int);
int ADC_GetFlagStatus(void *, uint32_t);
uint16_t ADC_GetDat(void *);
void ADC_ClearFlag(void *, uint32_t);
#endif
''',
}


def main() -> None:
    cc = os.environ.get("CC") or shutil.which("gcc") or shutil.which("cc")
    if not cc:
        raise AssertionError("host C compiler is required")
    with tempfile.TemporaryDirectory(prefix="adc_power_loss_") as td:
        directory = Path(td)
        for name, content in HEADERS.items():
            (directory / name).write_text(content, encoding="ascii")
        harness = directory / "harness.c"
        binary = directory / "adc_power_loss.exe"
        harness.write_text(HARNESS, encoding="ascii")
        build = subprocess.run(
            [cc, "-std=c99", "-Wall", "-Wextra", "-Werror",
             "-I", str(directory), "-I", str(ROOT / "include"),
             str(harness), str(ROOT / "src" / "adc_monitor.c"),
             "-o", str(binary)],
            cwd=ROOT, capture_output=True, text=True,
        )
        if build.returncode:
            raise AssertionError("ADC harness compile failed:\n" + build.stderr)
        run = subprocess.run([str(binary)], cwd=ROOT,
                             capture_output=True, text=True)
        if run.returncode:
            raise AssertionError("ADC harness failed:\n" + run.stdout + run.stderr)
        print(run.stdout.strip())


if __name__ == "__main__":
    main()
