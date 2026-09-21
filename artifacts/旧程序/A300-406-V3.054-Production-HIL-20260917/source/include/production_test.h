#ifndef PRODUCTION_TEST_H
#define PRODUCTION_TEST_H
#include <stdbool.h>
/* Local debug UART only. Never route SMS/platform commands here. */
bool production_test_command(const char *line);
/* 1 ms ISR: bounded GPIO sampling only; no parsing, I2C or printing. */
void production_test_tick(void);
#endif
