#include "debug_uart.h"
#include "config.h"
#include "n32l40x.h"
#include <stdarg.h>
#include <string.h>

static volatile uint32_t s_bytes_sent;
static volatile uint32_t s_wait_cycles;

void dbg_putchar(char c)
{
    uint32_t timeout = 100000;
    while (USART_GetFlagStatus(DBG_UART, USART_FLAG_TXDE) == RESET) {
        ++s_wait_cycles;
        if (--timeout == 0)
            return;
    }
    USART_SendData(DBG_UART, (uint8_t)c);
    ++s_bytes_sent;
}

uint32_t dbg_uart_bytes_sent(void) { return s_bytes_sent; }
uint32_t dbg_uart_wait_cycles(void) { return s_wait_cycles; }
void dbg_uart_stats_reset(void) { s_bytes_sent = 0U; s_wait_cycles = 0U; }

void dbg_puts(const char *s)
{
    while (*s) dbg_putchar(*s++);
}

static int print_uint_width(unsigned long v, unsigned base, int width, int zero_pad)
{
    char buf[32];
    int digits = 0, n = 0;
    if (v == 0) buf[digits++] = '0';
    while (v) { unsigned d = (unsigned)(v % base); buf[digits++] = d < 10 ? (char)('0' + d) : (char)('a' + d - 10); v /= base; }
    for (int pad = digits; pad < width; ++pad) { dbg_putchar((char)(zero_pad ? '0' : ' ')); n++; }
    for (int i = digits - 1; i >= 0; --i) { dbg_putchar(buf[i]); n++; }
    return n;
}

static int print_uint(unsigned long v, unsigned base)
{
    return print_uint_width(v, base, 0, 0);
}

/* print a signed long */
static int print_int(long v, unsigned base)
{
    int n = 0;
    unsigned long magnitude = (unsigned long)v;
    if (v < 0) { dbg_putchar('-'); n++; magnitude = 0UL - magnitude; }
    return n + print_uint(magnitude, base);
}

/* print a double with `prec` decimal places */
static int print_float(double f, int prec)
{
    int n = 0;
    if (f != f) { dbg_puts("nan"); return 3; }    /* NaN check */
    if (prec < 0) prec = 6;

    if (f < 0) { dbg_putchar('-'); n++; f = -f; }

    /* rounding */
    double round = 0.5;
    for (int i = 0; i < prec; i++) round /= 10.0;
    f += round;

    unsigned long ipart = (unsigned long)f;
    double frac = f - (double)ipart;

    n += print_uint(ipart, 10);

    if (prec > 0) {
        dbg_putchar('.'); n++;
        for (int i = 0; i < prec; i++) {
            frac *= 10.0;
            int digit = (int)frac;
            dbg_putchar((char)('0' + digit));
            frac -= digit;
            n++;
        }
    }
    return n;
}

/* PLACEHOLDER_PRINTF */

/* Supports: %d %i %u %x %X %s %c %% and %f with optional precision (%.2f) */
int dbg_printf(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    int count = 0;

    while (*fmt) {
        if (*fmt != '%') {
            dbg_putchar(*fmt++);
            count++;
            continue;
        }
        fmt++;  /* skip '%' */

        int width = 0, zero_pad = 0;
        if (*fmt == '0') { zero_pad = 1; fmt++; }
        while (*fmt >= '0' && *fmt <= '9') width = width * 10 + (*fmt++ - '0');
        /* parse optional precision ".N" */
        int prec = -1;
        if (*fmt == '.') {
            fmt++;
            prec = 0;
            while (*fmt >= '0' && *fmt <= '9')
                prec = prec * 10 + (*fmt++ - '0');
        }
        /* skip length modifiers like 'l' */
        while (*fmt == 'l' || *fmt == 'h') fmt++;

        char spec = *fmt++;
        switch (spec) {
        case 'd':
        case 'i': count += print_int(va_arg(ap, int), 10); break;
        case 'u': count += print_uint_width(va_arg(ap, unsigned), 10, width, zero_pad); break;
        case 'x':
        case 'X': count += print_uint_width(va_arg(ap, unsigned), 16, width, zero_pad); break;
        case 'f':
        case 'F': count += print_float(va_arg(ap, double), prec); break;
        case 's': {
            const char *s = va_arg(ap, const char *);
            if (!s) s = "(null)";
            while (*s) { dbg_putchar(*s++); count++; }
            break;
        }
        case 'c':
            dbg_putchar((char)va_arg(ap, int));
            count++;
            break;
        case '%':
            dbg_putchar('%');
            count++;
            break;
        default:
            dbg_putchar('%');
            dbg_putchar(spec);
            count += 2;
            break;
        }
    }

    va_end(ap);
    return count;
}

