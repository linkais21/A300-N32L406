#ifndef DEBUG_UART_H
#define DEBUG_UART_H

#include <stdint.h>

void dbg_init(void);
void dbg_putchar(char c);
void dbg_puts(const char *s);
int  dbg_printf(const char *fmt, ...);

#endif
