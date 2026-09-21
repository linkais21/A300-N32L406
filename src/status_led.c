#include "status_led.h"
#include "config.h"
#include "n32l40x.h"

void status_led_process(bool sleeping, bool gps_valid, uint32_t now_ms)
{
    static bool searching;
    static uint32_t search_start_ms;
    bool on = false;

    if (sleeping || gps_valid) {
        searching = false;
        on = !sleeping;
    } else {
        if (!searching) {
            search_start_ms = now_ms;
            searching = true;
        }
        on = ((uint32_t)(now_ms - search_start_ms) % 2000U) < 1000U;
    }
    /* D19 / Q3: high GPS_LED turns blue on. D20 belongs to the modem;
     * D26 belongs to ETA4056 STAT, with no independent MCU control. */
    if (on) GPIO_SetBits(GPS_LED_PORT, GPS_LED_PIN);
    else    GPIO_ResetBits(GPS_LED_PORT, GPS_LED_PIN);
}
