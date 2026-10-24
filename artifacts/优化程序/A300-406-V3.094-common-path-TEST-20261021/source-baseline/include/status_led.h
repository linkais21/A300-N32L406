#ifndef STATUS_LED_H
#define STATUS_LED_H
#include <stdbool.h>
#include <stdint.h>

/* Main-loop only; sleep takes priority over a retained GNSS fix. */
void status_led_process(bool sleeping, bool gps_valid, uint32_t now_ms);
#endif
