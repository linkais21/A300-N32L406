#ifndef RELAY_H
#define RELAY_H
#include <stdbool.h>
#include <stdint.h>
void relay_set(bool on);
bool relay_get(void);
bool relay_test_low(void);
void relay_test_high(void);
void relay_test_tick(void);
uint16_t relay_test_remaining(void);
#endif
