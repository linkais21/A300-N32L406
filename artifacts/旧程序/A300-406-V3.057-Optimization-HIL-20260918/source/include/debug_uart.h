#ifndef DEBUG_UART_H
#define DEBUG_UART_H

#include <stdint.h>

void dbg_init(void);
void dbg_putchar(char c);
void dbg_puts(const char *s);
int  dbg_printf(const char *fmt, ...);

/* Verbose diagnostics are disabled in Release by default. Define
 * DBG_LOG_LEVEL=2 for a diagnostic build that restores them. The disabled
 * helper remains a real variadic function, so its arguments are evaluated
 * while LTO can remove the unused format string and call. */
#ifndef DBG_LOG_LEVEL
#define DBG_LOG_LEVEL 1
#endif
#define DBG_LOG_LEVEL_VERBOSE 2
#if DBG_LOG_LEVEL >= DBG_LOG_LEVEL_VERBOSE
#define dbg_printf_verbose(...) dbg_printf(__VA_ARGS__)
#else
static inline int dbg_printf_verbose(const char *fmt, ...)
{
    (void)fmt;
    return 0;
}
#endif
#define DBG_PRINTF_VERBOSE(...) dbg_printf_verbose(__VA_ARGS__)

/* Lightweight counters used to quantify line-rate stalls without changing
 * the synchronous delivery contract. */
uint32_t dbg_uart_bytes_sent(void);
uint32_t dbg_uart_wait_cycles(void);
void dbg_uart_stats_reset(void);

#endif
