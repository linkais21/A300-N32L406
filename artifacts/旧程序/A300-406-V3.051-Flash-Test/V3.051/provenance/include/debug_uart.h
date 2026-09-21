#ifndef DEBUG_UART_H
#define DEBUG_UART_H

#include <stdint.h>

void dbg_init(void);
void dbg_putchar(char c);
void dbg_puts(const char *s);
int  dbg_printf(const char *fmt, ...);

/* Lightweight counters used to quantify line-rate stalls without changing
 * the synchronous delivery contract. */
uint32_t dbg_uart_bytes_sent(void);
uint32_t dbg_uart_wait_cycles(void);
void dbg_uart_stats_reset(void);

#endif
